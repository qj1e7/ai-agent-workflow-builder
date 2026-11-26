import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { request, type Locator, type Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

// What the n8n browser test of 16 Nov found: the Software watchlist had no In n8n tab, and only the In n8n tab said who held a
// workflow, so Alice was offered changes the platform then refused. Dana is a new Operator with n8n access who sets her n8n
// password, as the API suite's Member does, so she can hold a workflow. She never opens the watchlist, which other specs change.

const N8N_URL = process.env['N8N_URL'] ?? 'http://n8n:5678'
const SAFE_BLOCKS = 'Only our blocks and n8n’s safe ones are on, so every write waits for approval.'
const HELD = /Dana has it open in n8n since \d{1,2}:\d{2}\./
const AGENTS = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }]

interface MyN8n {
  readonly set_password_url: string | null
  readonly can_open: boolean
}

const main = (page: Page): Locator => page.getByRole('main')
const views = (page: Page): Locator => main(page).getByRole('group', { name: 'View' })
const openInN8n = (page: Page): Locator => main(page).getByRole('button', { name: /^Open in n8n editor/ })

/** A new Operator with n8n access, whose n8n account the platform made and whose password she set through its link. */
async function n8nMember(backend: Backend, display: string): Promise<string> {
  const email = `${display.toLowerCase()}-${randomUUID().slice(0, 8)}@example.test`
  const { id } = await backend.post<{ id: string }>('alice', '/api/v1/people', { email, display, operator: true }, undefined, [201])
  const given = await backend.send('PUT', 'alice', `/api/v1/people/${id}/n8n-access`, { n8n_access: true })
  expect(given.status, `Alice gives ${display} n8n access: ${JSON.stringify(given.body)}`).toBe(200)
  let link = ''
  await expect
    .poll(async () => (link = (await backend.get<MyN8n>(id, '/api/v1/me/n8n')).set_password_url ?? ''), { message: `the platform makes ${display}'s n8n account`, timeout: 90_000, intervals: [1_000] })
    .not.toBe('')
  const token = new URL(link).searchParams.get('token')
  expect(token, 'the link carries n8n’s invite token').toBeTruthy()
  const n8n = await request.newContext({ baseURL: N8N_URL })
  const accepted = await n8n.post('/rest/invitations/accept', { data: { token, firstName: display, lastName: 'Tester', password: `Holds-${randomUUID().slice(0, 12)}a1A` } })
  expect(accepted.status(), `n8n takes ${display}'s password: ${await accepted.text()}`).toBe(200)
  await n8n.dispose()
  await expect
    .poll(async () => (await backend.get<MyN8n>(id, '/api/v1/me/n8n')).can_open, { message: `n8n knows ${display} set her password`, timeout: 90_000, intervals: [1_000] })
    .toBe(true)
  return id
}

test.describe('who has a workflow open in n8n, and the watchlist in n8n', () => {
  let dana = ''
  let useCaseId = ''
  let watchlistId = ''

  test.beforeAll(async ({ backend }) => {
    test.setTimeout(240_000)
    dana = await n8nMember(backend, 'Dana')
    const body = { name: `Held ${randomUUID().slice(0, 6)}`, instruction: 'Check LangGraph for new releases.', agents: AGENTS, schedule: { day: 'monday', at: '09:00' }, on: true }
    useCaseId = (await backend.post<{ use_case_id: string }>('carol', '/api/v1/agent-use-cases', body, undefined, [201])).use_case_id
    const { watchlist } = await backend.get<{ watchlist: { use_case_id: string } | null }>('alice', '/api/v1/watchlist')
    watchlistId = watchlist?.use_case_id ?? (await backend.freshWatchlist('alice'))
  })

  test.afterAll(async ({ backend }) => {
    await backend.send('POST', dana, `/api/v1/use-cases/${useCaseId}/take-back`)
    await backend.delete('alice', `/api/v1/use-cases/${useCaseId}`, [200, 404])
    await backend.send('PUT', 'alice', `/api/v1/people/${dana}/n8n-access`, { n8n_access: false })
  })

  test('the Software watchlist has the In n8n tab every workflow has, with Open in n8n editor, and its workflow address lands there', async ({ browser }, info) => {
    const context = await devContext(browser, dana)
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/software')
    await expect(page.getByRole('banner')).toContainText('Dana')
    await expect(views(page).getByRole('button')).toHaveText(['Summary', 'In n8n'])
    await views(page).getByRole('button', { name: 'In n8n' }).click()
    await expect(page).toHaveURL(/\/workflows\/[^/?]+\?view=n8n$/)
    await expect(main(page)).toContainText(SAFE_BLOCKS)
    await expect(main(page).locator('svg title').first()).toHaveText(/ in n8n: /)
    await expect(openInN8n(page), 'she can open n8n, so the editor is one press away').toBeVisible()
    await expect(main(page).locator(':is(button, input, select, textarea):disabled, [aria-disabled="true"]')).toHaveCount(0)
    await expectAccessible(page, path.join(OUT, 'axe'), 'holds-watchlist-in-n8n')
    await shot(page, info, 'holds-watchlist-in-n8n-dana')

    await page.goto(`/workflows/${watchlistId}?view=n8n`)
    await expect(page, 'the Planner’s link for the watchlist keeps the tab').toHaveURL(/\/workflows\/[^/?]+\?view=n8n$/)
    await expect(openInN8n(page)).toBeVisible()
    assertClean(watch)
    await context.close()

    const alice = await devContext(browser, 'alice')
    const hers = await alice.newPage()
    await hers.goto('/software?view=n8n')
    await expect(hers.getByRole('heading', { level: 1 })).toHaveText('Software watchlist')
    await expect(views(hers), 'Alice has no n8n access, so no tab').toHaveCount(0)
    await expect(main(hers)).not.toContainText(SAFE_BLOCKS)
    await alice.close()
  })

  test('everyone sees who has it open on its Summary and its Workflows row, and Alice is offered no change the platform would refuse', async ({ backend, browser }, info) => {
    const opened = await backend.send('POST', dana, `/api/v1/use-cases/${useCaseId}/open-in-n8n`)
    expect(opened.status, `Dana opens it in n8n: ${JSON.stringify(opened.body)}`).toBe(200)

    const alice = await devContext(browser, 'alice')
    const page = await alice.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${useCaseId}`)
    await expect(main(page)).toContainText(HELD)
    await expect(main(page)).toContainText('Ask Dana, or anyone with n8n access, to take it back.')
    const when = main(page).getByRole('region', { name: 'When' })
    await expect(when).toContainText('Can’t change it while Dana has it open in n8n.')
    await expect(when.getByRole('button'), 'Change when it runs would be refused after Save').toHaveCount(0)
    for (const refused of ['Undo', 'Add the approval step back', 'Resume']) await expect(main(page).getByRole('button', { name: refused, exact: true })).toHaveCount(0)
    await expect(main(page).getByRole('button', { name: 'Pause' }), 'Pause still works while it is held').toBeVisible()
    await expect(main(page).locator(':is(button, input, select, textarea):disabled, [aria-disabled="true"]')).toHaveCount(0)
    await expectAccessible(page, path.join(OUT, 'axe'), 'holds-summary-alice')
    await shot(page, info, 'holds-summary-alice')

    await page.goto('/workflows')
    await expect(page.locator(`li[data-workflow-id="${useCaseId}"]`), 'the row says it in the same words').toContainText('Dana has it open in n8n')
    await shot(page, info, 'holds-workflows-row-alice')
    assertClean(watch)
    await alice.close()

    const bob = await devContext(browser, 'bob')
    const his = await bob.newPage()
    await his.goto(`/workflows/${useCaseId}`)
    await expect(main(his)).toContainText(HELD)
    await bob.close()

    const holder = await devContext(browser, dana)
    const hers = await holder.newPage()
    await hers.goto(`/workflows/${useCaseId}`)
    await expect(main(hers)).toContainText(/You have it open in n8n since \d{1,2}:\d{2}\./)
    await expect(main(hers).getByRole('button', { name: 'Take it back' }).first()).toBeVisible()
    await holder.close()
  })

  test('once Dana takes it back, Alice can change when it runs again and no line says it is held', async ({ backend, browser }) => {
    const back = await backend.send('POST', dana, `/api/v1/use-cases/${useCaseId}/take-back`)
    expect(back.status, `Dana takes it back: ${JSON.stringify(back.body)}`).toBe(200)
    const alice = await devContext(browser, 'alice')
    const page = await alice.newPage()
    await page.goto(`/workflows/${useCaseId}`)
    await expect(main(page).getByRole('region', { name: 'When' }).getByRole('button', { name: 'Change when it runs' })).toBeVisible()
    await expect(main(page)).not.toContainText('has it open in n8n')
    await page.goto('/workflows')
    await expect(page.locator(`li[data-workflow-id="${useCaseId}"]`)).not.toContainText('has it open in n8n')
    await alice.close()
  })
})
