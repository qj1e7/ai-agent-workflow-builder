import { randomUUID } from 'node:crypto'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './support/test'
import { devContext, shot } from './support/ui'

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
const rowOf = (page: Page, useCaseId: string) => page.locator(`li[data-workflow-id="${useCaseId}"]`)
const nextRun = (page: Page) => page.locator('dt', { hasText: 'Next run' }).locator('xpath=following-sibling::dd[1]')
const VERSION_CHECKER = { card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }

async function ensureWatchlistOn(request: APIRequestContext, useCaseId: string): Promise<void> {
  const response = await request.post(`/api/v1/use-cases/${useCaseId}/resume`, { headers: { 'X-Dev-User': 'alice' } })
  expect(response.status(), 'the watchlist is on').toBe(200)
}

async function agentWorkflow(request: APIRequestContext, name: string): Promise<string> {
  const response = await request.post('/api/v1/agent-use-cases', {
    headers: { 'X-Dev-User': 'alice' },
    data: { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [VERSION_CHECKER] },
  })
  expect(response.status(), 'alice makes an agent workflow').toBe(201)
  return ((await response.json()) as { use_case_id: string }).use_case_id
}

test('alice opens the Software watchlist from Workflows, presses Run now, and lands on the new run’s page', async ({ browser, backend, request }, info) => {
  const useCaseId = await backend.freshWatchlist('alice')
  await ensureWatchlistOn(request, useCaseId)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(heading(page)).toHaveText('Workflows')
  const row = rowOf(page, useCaseId)
  await expect(row).toContainText('On')
  await row.getByRole('link', { name: 'Software watchlist' }).click()
  await expect(page).toHaveURL(new RegExp(`/workflows/${useCaseId}$`))
  await expect(heading(page)).toHaveText('Software watchlist')
  await shot(page, info, 'p9-04-workflow-page')

  const before = (await backend.runs('alice')).filter((run) => run.use_case_name === 'Software watchlist').length
  await page.getByRole('button', { name: 'Run now' }).click()
  await expect(page).toHaveURL(/\/runs\/run_[A-Za-z0-9]+$/)
  const runId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
  const run = await backend.run(runId)
  expect(run.use_case_name).toBe('Software watchlist')
  expect(run.started_by).toBe('alice')
  expect((await backend.runs('alice')).filter((r) => r.use_case_name === 'Software watchlist')).toHaveLength(before + 1)
  await expect(heading(page)).toBeVisible()
  await shot(page, info, 'p9-04-run-now')
  await context.close()
})

test('alice pauses the Software watchlist, its next run reads Paused, and resuming shows a date again', async ({ browser, backend, request }) => {
  const useCaseId = await backend.freshWatchlist('alice')
  await ensureWatchlistOn(request, useCaseId)
  const saved = await request.put('/api/v1/watchlist/schedule', { headers: { 'X-Dev-User': 'alice' }, data: { day: 'monday', at: '09:00' } })
  expect(saved.status()).toBe(200)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${useCaseId}`)
  await expect(heading(page)).toHaveText('Software watchlist')
  await expect(nextRun(page)).toHaveText(/^(Today|[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}), \d{1,2}:\d{2}/)

  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(nextRun(page)).toHaveText('Paused')
  await expect(page.getByRole('button', { name: 'Resume' })).toBeFocused()
  await expect(page.getByRole('button', { name: 'Run now' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Resume' }).click()
  await expect(nextRun(page)).toHaveText(/^(Today|[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}), \d{1,2}:\d{2}/)
  await expect(page.getByRole('button', { name: 'Run now' })).toBeVisible()
  await context.close()
})

test('alice deletes a workflow, it leaves the list, and Undo puts it back', async ({ browser, request }, info) => {
  const name = `p9 delete ${randomUUID().slice(0, 6)}`
  const useCaseId = await agentWorkflow(request, name)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${useCaseId}`)
  await expect(heading(page)).toHaveText(name)
  await page.getByRole('button', { name: 'Delete' }).click()
  const dialog = page.getByRole('alertdialog', { name: `Delete ${name}?` })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Delete workflow' }).click()

  await expect(page).toHaveURL(/\/workflows$/)
  await expect(page.getByRole('button', { name: 'Undo' })).toBeFocused()
  await expect(rowOf(page, useCaseId)).toHaveCount(0)
  await shot(page, info, 'p9-04-deleted')
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(rowOf(page, useCaseId)).toBeVisible()
  await expect(rowOf(page, useCaseId).getByRole('link', { name })).toBeFocused()
  const listed = await request.get('/api/v1/use-cases', { headers: { 'X-Dev-User': 'alice' } })
  expect(((await listed.json()) as { use_cases: { use_case_id: string }[] }).use_cases.map((item) => item.use_case_id)).toContain(useCaseId)
  await context.close()
})

test('bob sees who may approve and the recent runs, with no Run now, Pause or Delete', async ({ browser, backend, request }, info) => {
  const useCaseId = await backend.freshWatchlist('alice')
  await ensureWatchlistOn(request, useCaseId)
  await backend.checkNow('alice', useCaseId)
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/workflows/${useCaseId}`)
  await expect(heading(page)).toHaveText('Software watchlist')
  await expect(page.getByRole('main')).toContainText('Any Approver except the people who start or own it')
  await expect(page.getByRole('region', { name: 'Recent runs' }).getByRole('link').first()).toBeVisible()
  for (const name of ['Run now', 'Pause', 'Resume', 'Delete']) await expect(page.getByRole('button', { name })).toHaveCount(0)
  await shot(page, info, 'p9-04-approver')
  await context.close()
})
