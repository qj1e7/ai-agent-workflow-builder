import { randomUUID } from 'node:crypto'
import type { APIRequestContext, Page } from '@playwright/test'
import { MOCK_MODEL, MOCK_MODEL_URL, SettingsApi } from './support/settings'
import { expect, test } from './support/test'
import { devContext, shot } from './support/ui'

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
const rowOf = (page: Page, useCaseId: string) => page.locator(`li[data-workflow-id="${useCaseId}"]`)
const nextRun = (page: Page) => page.locator('dt', { hasText: 'Next run' }).locator('xpath=following-sibling::dd[1]')
const VERSION_CHECKER = { card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }

async function connectMockModel(baseURL: string): Promise<void> {
  const settings = await SettingsApi.connect(baseURL)
  try {
    if ((await settings.model()).active?.base_url === MOCK_MODEL_URL) return
    const saved = await settings.send<{ status: string }>('alice', 'PUT', '/api/v1/settings/model', { style: 'anthropic', base_url: MOCK_MODEL_URL, model: MOCK_MODEL, api_key: 'p9-live-key-not-real' })
    expect(saved.status, `alice saves the mock model: ${JSON.stringify(saved.body)}`).toBe(200)
    await settings.confirmAddress('bob')
    expect((await settings.model()).active?.base_url, 'the mock model is active').toBe(MOCK_MODEL_URL)
  } finally {
    await settings.dispose()
  }
}

async function agentWorkflow(request: APIRequestContext, label: string): Promise<{ id: string; name: string }> {
  const name = `p9 ${label} ${randomUUID().slice(0, 6)}`
  const response = await request.post('/api/v1/agent-use-cases', {
    headers: { 'X-Dev-User': 'alice' },
    data: { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [VERSION_CHECKER] },
  })
  expect(response.status(), 'alice makes an agent workflow').toBe(201)
  return { id: ((await response.json()) as { use_case_id: string }).use_case_id, name }
}

test('alice opens a workflow from Workflows, presses Run now, and lands on the new run’s page', async ({ browser, backend, request, baseURL }, info) => {
  await connectMockModel(String(baseURL))
  const workflow = await agentWorkflow(request, 'run now')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(heading(page)).toHaveText('Workflows')
  const row = rowOf(page, workflow.id)
  await expect(row).toContainText('On')
  await row.getByRole('link', { name: workflow.name }).click()
  await expect(page).toHaveURL(new RegExp(`/workflows/${workflow.id}$`))
  await expect(heading(page)).toHaveText(workflow.name)
  await shot(page, info, 'p9-04-workflow-page')

  await page.getByRole('button', { name: 'Run now' }).click()
  await expect(page).toHaveURL(/\/runs\/run_[A-Za-z0-9]+$/)
  const runId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
  const run = await backend.run(runId)
  expect(run.use_case_name).toBe(workflow.name)
  expect(run.started_by).toBe('alice')
  expect((await backend.runs('alice')).filter((r) => r.use_case_name === workflow.name)).toHaveLength(1)
  await expect(heading(page)).toBeVisible()
  await shot(page, info, 'p9-04-run-now')
  await context.close()
})

test('alice pauses a workflow, its next run reads Paused and Run now goes, and resuming brings them back', async ({ browser, request }) => {
  const workflow = await agentWorkflow(request, 'pause')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)
  await expect(nextRun(page)).toHaveText('Not scheduled')

  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(nextRun(page)).toHaveText('Paused')
  await expect(page.getByRole('button', { name: 'Resume' })).toBeFocused()
  await expect(page.getByRole('button', { name: 'Run now' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Resume' }).click()
  await expect(nextRun(page)).toHaveText('Not scheduled')
  await expect(page.getByRole('button', { name: 'Run now' })).toBeVisible()
  await context.close()
})

test('alice deletes a workflow, it leaves the list, and Undo puts it back', async ({ browser, request }, info) => {
  const { id: useCaseId, name } = await agentWorkflow(request, 'delete')
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
  await expect(page.getByText('Put back.', { exact: true }).last()).toBeVisible()
  const listed = await request.get('/api/v1/use-cases', { headers: { 'X-Dev-User': 'alice' } })
  expect(((await listed.json()) as { use_cases: { use_case_id: string }[] }).use_cases.map((item) => item.use_case_id)).toContain(useCaseId)
  await context.close()
})

test('bob sees who may approve and the recent runs, with no Run now, Pause or Delete', async ({ browser, backend, request, baseURL }, info) => {
  await connectMockModel(String(baseURL))
  const workflow = await agentWorkflow(request, 'approver')
  await backend.checkNow('alice', workflow.id)
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)
  await expect(page.getByRole('main')).toContainText('Any Approver except the people who start or own it')
  await expect(page.getByRole('region', { name: 'Recent runs' }).getByRole('link').first()).toBeVisible()
  for (const name of ['Run now', 'Pause', 'Resume', 'Delete']) await expect(page.getByRole('button', { name })).toHaveCount(0)
  await shot(page, info, 'p9-04-approver')
  await context.close()
})

test('the Software watchlist opens on the Software page, from its row and from its old address', async ({ browser, backend }) => {
  const watchlist = await backend.freshWatchlist('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const link = rowOf(page, watchlist).getByRole('link', { name: 'Software watchlist' })
  await expect(link).toHaveAttribute('href', '/software')
  await link.click()
  await expect(page).toHaveURL(/\/software$/)
  await expect(heading(page)).toHaveText('Software watchlist')
  await page.goto(`/workflows/${watchlist}`)
  await expect(page).toHaveURL(/\/software$/)
  await expect(heading(page)).toHaveText('Software watchlist')
  await context.close()
})
