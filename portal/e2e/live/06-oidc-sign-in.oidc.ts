import { expect, request, type Browser, type Page, type Response, type TestInfo } from '@playwright/test'
import { assertClean, watchPage, type Watch } from '../support/test'
import type { Backend } from './support/stack'
import { test } from './support/test'
import { openContext, shot } from './support/ui'

const AUTHORITY = process.env['MOCK_OIDC_URL'] ?? 'http://mock-oidc:8080/default'
const RENEWAL_MS = 120_000

interface Person {
  readonly page: Page
  readonly watch: Watch
  readonly grants: string[]
  readonly tokens: string[]
  readonly devHeaders: string[]
}

async function signIn(browser: Browser, backend: Backend, user: string, path: string, info: TestInfo, formShot?: string): Promise<Person> {
  const context = await openContext(browser)
  const page = await context.newPage()
  const person: Person = { page, watch: watchPage(page), grants: [], tokens: [], devHeaders: [] }
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
  page.on('request', (request) => {
    request
      .allHeaders()
      .then((headers) => {
        if ('x-dev-user' in headers) person.devHeaders.push(request.url())
      })
      // A request still in flight when the context closes cannot be read, and it has nothing left to send.
      .catch(() => undefined)
  })

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

test('alice signs in and sees her name, bob signs in at a deep link, and signing out ends the session', async ({ browser, backend }, info) => {
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
  await expect(alice.page.getByRole('heading', { level: 1 })).toContainText('Alice')
  await expect(alice.page.getByRole('button', { name: /Test controls/ }), 'real sign-in has no test controls').toHaveCount(0)
  await expect(alice.page.getByText('Act as'), 'real sign-in has no way to act as someone else').toHaveCount(0)
  await shot(alice.page, info, 'oidc-02-signed-in-alice')

  const me = await backend.get<{ id: string; display: string; roles: string[] }>('alice', '/api/v1/me')
  expect(me, 'the platform maps the token to alice').toEqual({ id: '0a11ce00-0000-4000-8000-000000000001', display: 'Alice', roles: ['operator', 'approver'] })

  for (const label of ['Workflows', 'Software watchlist', 'Agent library', 'Home']) {
    await alice.page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: label, exact: true }).click()
    await expect(alice.page.getByRole('heading', { level: 1 })).toBeVisible()
  }
  await alice.page.reload()
  await expect(header, 'a reload keeps alice signed in').toContainText('Alice')
  expect(alice.devHeaders, 'no request from the page carries X-Dev-User').toEqual([])

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
  await expect(header, 'a reload after the renewal keeps alice signed in').toContainText('Alice')
  expect(alice.devHeaders, 'still no request carries X-Dev-User').toEqual([])

  const bob = await signIn(browser, backend, 'bob', '/agents', info)
  await expect(bob.page, 'bob lands on the deep link he asked for').toHaveURL(/\/agents$/)
  await expect(bob.page.getByRole('heading', { level: 1 })).toHaveText('Agent library')
  await expect(bob.page.getByRole('banner')).toContainText('Bob')
  await expect(bob.page.getByRole('banner')).toContainText('Approver')
  await expect(bob.page.getByRole('banner')).not.toContainText('Operator')
  await shot(bob.page, info, 'oidc-03-bob-deep-link')

  const chip = bob.page.getByRole('banner').getByRole('button', { name: /Bob/ })
  await chip.focus()
  await bob.page.keyboard.press('Enter')
  await expect(chip, 'Enter on the chip opens the panel').toHaveAttribute('aria-expanded', 'true')
  await expect(bob.page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  await bob.page.keyboard.press('Escape')
  await expect(bob.page.getByRole('button', { name: 'Sign out' }), 'Escape closes the panel').toHaveCount(0)
  await expect(chip, 'Escape puts focus back on the chip').toBeFocused()
  await bob.page.keyboard.press('Enter')
  await expect(bob.page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  await shot(bob.page, info, 'oidc-04-sign-out-panel')
  await bob.page.getByRole('button', { name: 'Sign out' }).click()
  await expect(bob.page, 'sign-out comes back to the Portal').toHaveURL(/\/signed-out(\?|$)/)
  await expect(bob.page.getByRole('button', { name: 'Sign in' }), 'a signed-out person is offered sign-in, not sent straight back').toBeVisible()
  await shot(bob.page, info, 'oidc-05-signed-out')
  expect(bob.devHeaders, 'bob sent no X-Dev-User either').toEqual([])

  assertClean(alice.watch)
  assertClean(bob.watch)
  await alice.page.context().close()
  await bob.page.context().close()
})
