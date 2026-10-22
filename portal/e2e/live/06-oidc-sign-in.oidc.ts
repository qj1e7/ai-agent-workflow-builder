import { expect, request, type Browser, type Page, type Response, type TestInfo } from '@playwright/test'
import { headline } from '../support/flows'
import { assertClean, watchPage, type Watch } from '../support/test'
import type { Backend } from './support/stack'
import { test } from './support/test'
import { CATCH_UP_MS, openContext, runExampleFromBuilder, shot } from './support/ui'

const AUTHORITY = process.env['MOCK_OIDC_URL'] ?? 'http://mock-oidc:8080/default'
const OWN_WORK = 'You started this run, so another Approver must decide.'
/** The mock provider's tokens last 120 s, so the Portal renews about a minute after sign-in. */
const RENEWAL_MS = 120_000

interface Person {
  readonly page: Page
  readonly watch: Watch
  /** Every grant the Portal sent to the token endpoint, in order: authorization_code, then refresh_token for each renewal. */
  readonly grants: string[]
  readonly tokens: string[]
}

/**
 * Opens the Portal at `path` in a new browser context, signs in as `user` through the provider's own form, and keeps every access
 * token the Portal receives. The backend's calls for `user` then carry the newest of them, so the checks below use the very token the
 * Portal holds.
 */
async function signIn(browser: Browser, backend: Backend, user: string, path: string, info: TestInfo, formShot?: string): Promise<Person> {
  const context = await openContext(browser)
  const page = await context.newPage()
  const person: Person = { page, watch: watchPage(page), grants: [], tokens: [] }
  const record = async (response: Response): Promise<void> => {
    if (response.request().method() !== 'POST' || response.url() !== `${AUTHORITY}/token` || !response.ok()) return
    const { access_token: token } = (await response.json()) as { access_token?: string }
    person.grants.push(new URLSearchParams(response.request().postData() ?? '').get('grant_type') ?? '')
    if (token) {
      person.tokens.push(token)
      backend.signedIn(user, { Authorization: `Bearer ${token}` })
    }
  }
  page.on('response', (response) => void record(response))

  await page.goto(path)
  const username = page.locator('input[name="username"]')
  await expect(username, 'the Portal sends a signed-out person to the identity provider').toBeVisible()
  if (formShot) await shot(page, info, formShot)
  await username.fill(user)
  await page.locator('input[type="submit"]').click()
  await expect(page, 'sign-in returns to the page the person asked for').toHaveURL(new RegExp(`${path === '/' ? '/$' : path}`))
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect.poll(() => person.tokens.length, { message: `the Portal holds an access token for ${user}` }).toBeGreaterThan(0)
  return person
}

test('alice signs in and starts a run, cannot approve it herself, and bob signs in and approves it once', async ({ browser, backend }, info) => {
  test.setTimeout(360_000)
  const provider = await request.newContext()
  await expect
    .poll(async () => (await provider.get(AUTHORITY.replace(/\/[^/]+$/, '/isalive')).catch(() => null))?.ok() ?? false, {
      message: 'the mock identity provider is up',
      timeout: 60_000,
    })
    .toBe(true)
  await provider.dispose()

  const alice = await signIn(browser, backend, 'alice', '/', info, 'oidc-01-sign-in-form')
  const header = alice.page.getByRole('banner')
  await expect(header, 'the header names the person the token belongs to').toContainText('Alice')
  await expect(header, 'the header shows her roles from the roles claim').toContainText('Operator and Approver')
  await expect(header.getByRole('button', { name: /Switch user/ }), 'real sign-in has no dev switcher').toHaveCount(0)
  await shot(alice.page, info, 'oidc-02-signed-in-alice')

  const me = await backend.get<{ id: string; display: string; roles: string[] }>('alice', '/api/v1/me')
  expect(me, 'the platform maps the token to alice').toEqual({ id: '0a11ce00-0000-4000-8000-000000000001', display: 'Alice', roles: ['operator', 'approver'] })

  const ticketsBefore = await backend.tickets()
  const runId = await runExampleFromBuilder(alice.page, info, 'oidc-run')
  await backend.waitForState(runId, ['awaiting_approval'])
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing is written while the run waits').toEqual([])

  const approval = alice.page.getByRole('region', { name: 'Approval' })
  await expect(approval.getByText(OWN_WORK), 'alice is told why she cannot decide').toBeVisible({ timeout: CATCH_UP_MS })
  await expect(approval.getByRole('button', { name: 'Approve', exact: true }), 'alice has no Approve button').toHaveCount(0)
  await shot(alice.page, info, 'oidc-03-alice-cannot-approve')

  const approvalId = await backend.approvalIdOf(runId)
  const { digest } = await backend.get<{ digest: string }>('alice', `/api/v1/approvals/${approvalId}`)
  const refusal = await alice.page.request.post(`/api/v1/approvals/${approvalId}/decisions`, {
    headers: backend.proofOf('alice'),
    data: { step: 0, verdict: 'approve', digest },
  })
  expect(refusal.status(), 'the backend refuses alice with her own token').toBe(403)
  expect(((await refusal.json()) as { refusal: string }).refusal).toBe('own_work')

  const devHeader = await alice.page.request.get('/api/v1/runs', { headers: { 'X-Dev-User': 'bob' } })
  expect(devHeader.status(), 'the dev header means nothing with real sign-in').toBe(401)
  expect(devHeader.headers()['www-authenticate']).toBe('Bearer')

  await expect
    .poll(() => alice.grants.filter((grant) => grant === 'refresh_token').length, {
      message: 'the Portal renews the token silently before it expires',
      timeout: RENEWAL_MS,
    })
    .toBeGreaterThan(0)
  expect(new Set(alice.tokens).size, 'the renewal brought a new access token').toBeGreaterThan(1)
  expect((await backend.get<{ id: string }>('alice', '/api/v1/me')).id, 'the renewed token still signs alice in').toBe(me.id)
  await alice.page.reload()
  await expect(alice.page.getByRole('banner'), 'a reload keeps alice signed in').toContainText('Alice')

  const bob = await signIn(browser, backend, 'bob', `/runs/${runId}`, info)
  await expect(bob.page.getByRole('banner')).toContainText('Bob')
  await expect(bob.page.getByRole('banner')).toContainText('Approver')
  const bobsApproval = bob.page.getByRole('region', { name: 'Approval' })
  const approve = bobsApproval.getByRole('button', { name: 'Approve', exact: true })
  await expect(approve, 'bob can decide').toBeVisible({ timeout: CATCH_UP_MS })
  await shot(bob.page, info, 'oidc-04-signed-in-bob')
  await approve.click()

  const finished = await backend.waitForState(runId, ['succeeded'])
  expect(finished.outcome).toBe('written')
  const written = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(written, 'exactly one ticket for this run').toHaveLength(1)
  const key = written[0]?.key ?? ''
  expect(key).toMatch(/^MOCK-\d+$/)
  expect((await backend.tickets()).length - ticketsBefore.length, 'one ticket more than before the run').toBe(1)
  await expect(headline(bob.page), 'the Tracker ends on the ticket key').toHaveText(`${key} is in Jira`, { timeout: CATCH_UP_MS })
  await shot(bob.page, info, 'oidc-05-run-written')

  await bob.page.getByRole('button', { name: 'Sign out' }).click()
  await expect(bob.page, 'sign-out comes back to the Portal').toHaveURL(/\/signed-out(\?|$)/)
  await expect(bob.page.getByRole('button', { name: 'Sign in' }), 'a signed-out person is offered sign-in, not sent straight back').toBeVisible()
  await shot(bob.page, info, 'oidc-06-signed-out')

  assertClean(alice.watch)
  assertClean(bob.watch)
  await alice.page.context().close()
  await bob.page.context().close()
})
