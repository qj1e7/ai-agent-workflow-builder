import AxeBuilder from '@axe-core/playwright'
import { expect, request, test, type APIRequestContext, type Browser, type Page, type Request } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { Backend } from '../live/support/stack'
import { devContext } from '../live/support/ui'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p9'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const MOCK_MODEL_URL = process.env['MOCK_MODEL_URL'] ?? 'http://mock-model:8300'
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const NOT_BUILT = 'This page is not built yet.'
const WHO_APPROVES = 'Any Approver except the people who start or own it'
const MANAGE = ['Run now', 'Pause', 'Resume', 'Delete']
const VERSION_CHECKER = { card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }
const SETTLED = ['awaiting_approval', 'succeeded', 'failed', 'rejected']
const DATE = /^(Today|[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}( \d{4})?), \d{1,2}:\d{2}$/
const LONGEST_PLAIN_TOAST_MS = 10_000
const PERF_WORKFLOW = 'p9 perf twenty runs'
const RETIRED = /\b(room[ _-]?lead|release[ _-]?check\w*|use[ _-]?cases?|usecase|flint|forge|striker|spark map|scout|analyst|messenger|clerk|fixer|kindling|firebreak|ember)\b/i

interface UseCase {
  use_case_id: string
  name: string
  instruction: string
  state: 'on' | 'paused'
  next_run_at: string | null
}

interface Run {
  run_id: string
  use_case_id: string
  state: string
  started_by: string
}

interface Workflow {
  id: string
  name: string
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

function workflowSavedBySetup(lane: number, by: string): Workflow & Record<string, unknown> {
  const file = path.join(laneDir(lane), 'workflow.json')
  if (!existsSync(file)) throw new Error(`no ${file}; run ${by}, which makes the workflow first`)
  return JSON.parse(readFileSync(file, 'utf8')) as Workflow & Record<string, unknown>
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = false): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })
const rowOf = (page: Page, useCaseId: string) => page.locator(`li[data-workflow-id="${useCaseId}"]`)
const nextRunOf = (page: Page) => page.locator('dt', { hasText: 'Next run' }).locator('xpath=following-sibling::dd[1]')
const whenOf = (page: Page) => page.locator('dt', { hasText: /^When$/ }).locator('xpath=following-sibling::dd[1]')
const recentRuns = (page: Page) => page.getByRole('region', { name: 'Recent runs' })
const toastCard = (page: Page) => page.locator('[class*="dock"] > div')
const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })

async function mainButtons(page: Page): Promise<string[]> {
  return (await page.getByRole('main').getByRole('button').allInnerTexts()).map((label) => label.trim())
}

async function withBackend<T>(act: (backend: Backend, api: APIRequestContext) => Promise<T>): Promise<T> {
  const backend = await Backend.connect(BASE_URL)
  const api = await request.newContext({ baseURL: BASE_URL })
  try {
    return await act(backend, api)
  } finally {
    await backend.dispose()
    await api.dispose()
  }
}

async function call(api: APIRequestContext, user: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', url: string, data?: unknown, headers: Record<string, string> = {}): Promise<{ status: number; body: unknown }> {
  const response = await api.fetch(url, { method, headers: { 'X-Dev-User': user, ...headers }, ...(data === undefined ? {} : { data }) })
  const text = await response.text()
  let body: unknown = text
  try {
    body = text ? (JSON.parse(text) as unknown) : null
  } catch {
    body = text
  }
  return { status: response.status(), body }
}

async function listedWorkflows(api: APIRequestContext): Promise<UseCase[]> {
  return ((await call(api, 'alice', 'GET', '/api/v1/use-cases')).body as { use_cases: UseCase[] }).use_cases
}

async function useCaseOf(api: APIRequestContext, id: string): Promise<UseCase | undefined> {
  return (await listedWorkflows(api)).find((item) => item.use_case_id === id)
}

async function runsOf(api: APIRequestContext, id: string): Promise<Run[]> {
  const { body } = await call(api, 'alice', 'GET', '/api/v1/runs')
  return (body as { runs: Run[] }).runs.filter((run) => run.use_case_id === id)
}

async function agentWorkflow(api: APIRequestContext, label: string, user = 'alice'): Promise<Workflow> {
  const name = `p9 ${label} ${randomUUID().slice(0, 6)}`
  const made = await call(api, user, 'POST', '/api/v1/agent-use-cases', { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [VERSION_CHECKER] })
  expect(made.status, `${user} makes ${name}: ${JSON.stringify(made.body)}`).toBe(201)
  return { id: (made.body as { use_case_id: string }).use_case_id, name }
}

async function connectMockModel(api: APIRequestContext): Promise<void> {
  const active = (await call(api, 'alice', 'GET', '/api/v1/settings/model')).body as { active: { base_url: string } | null }
  if (active.active?.base_url === MOCK_MODEL_URL) return
  const saved = await call(api, 'alice', 'PUT', '/api/v1/settings/model', { style: 'anthropic', base_url: MOCK_MODEL_URL, model: 'mock-model', api_key: 'p9-mock-key-not-real' })
  expect(saved.status, `save the mock model: ${JSON.stringify(saved.body)}`).toBe(200)
  if ((saved.body as { status: string }).status === 'awaiting_confirmation') {
    const pending = ((await call(api, 'bob', 'GET', '/api/v1/settings/model')).body as { pending: { digest: string } }).pending
    const confirmed = await call(api, 'bob', 'POST', '/api/v1/settings/model/address-decision', { verdict: 'confirm', digest: pending.digest })
    expect(confirmed.status, 'bob confirms the mock model address').toBeLessThan(300)
  }
  expect(((await call(api, 'alice', 'GET', '/api/v1/settings/model')).body as { active: unknown }).active, 'the mock model is active').not.toBeNull()
}

async function workflowWithARun(backend: Backend, api: APIRequestContext, label: string): Promise<Workflow & { runId: string; runState: string }> {
  await connectMockModel(api)
  const workflow = await agentWorkflow(api, label)
  const runId = await backend.checkNow('alice', workflow.id)
  const run = await backend.waitForState(runId, SETTLED, 180_000)
  return { ...workflow, runId, runState: run.state }
}

test('@lane1-trunk trunk has no Workflows page', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(h1(page)).toHaveText('Workflows')
  await shotTo(page, 1, 'p9-list-trunk.png')
  save(1, 'p9-list-trunk.json', { target: 'trunk', main: await page.getByRole('main').innerText() })
  await expect(page.getByRole('main')).toContainText(NOT_BUILT)
  await context.close()
})

test('@lane1 two seeded workflows, each with a run: On or Paused and the latest run are separate facts', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (backend, api) => {
    const on = await workflowWithARun(backend, api, 'lane1 on')
    const paused = await workflowWithARun(backend, api, 'lane1 paused')
    expect((await call(api, 'alice', 'POST', `/api/v1/use-cases/${paused.id}/pause`)).status).toBe(200)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/workflows')
    await expect(h1(page)).toHaveText('Workflows')
    await expect(page.getByRole('main')).not.toContainText(NOT_BUILT)
    await page.locator('#find-workflows').fill('p9 lane1')
    const facts: Record<string, unknown>[] = []
    for (const workflow of [on, paused]) {
      const row = rowOf(page, workflow.id)
      await expect(row).toBeVisible()
      const pills = (await row.locator('[class*="pills"] > span').allInnerTexts()).map((pill) => pill.trim())
      const line = (await row.locator('h2 + p').innerText()).trim()
      const next = (await row.locator('[class*="next"]').innerText()).trim()
      facts.push({ ...workflow, pills, line, next, link: await row.locator('h2 a').getAttribute('href') })
    }
    await shotTo(page, 1, 'p9-list.png', true)
    save(1, 'p9-list.json', { target: TARGET, facts })
    const [onRow, pausedRow] = facts as { pills: string[]; line: string; next: string; link: string; id: string; runState: string }[]
    expect(onRow?.pills[0]).toBe('On')
    expect(pausedRow?.pills[0]).toBe('Paused')
    for (const row of [onRow, pausedRow]) {
      expect(row?.line, 'the latest run line says when it ran and what happened').toMatch(/^Today \d{1,2}:\d{2}: \S/)
      expect(row?.line, 'the latest run line is apart from the On or Paused pill').not.toMatch(/\b(On|Paused)\b/)
      if (row?.runState === 'awaiting_approval') expect(row.line).toContain('waiting for a yes')
      expect(row?.link).toBe(`/workflows/${row?.id ?? ''}`)
    }
    expect(onRow?.next).toBe('Not scheduled')
    expect(pausedRow?.next).toBe('Next: Paused')
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 alice presses Run now and the run page opens on the new run', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    await connectMockModel(api)
    const workflow = await agentWorkflow(api, 'lane2 run now')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${workflow.id}`)
    await expect(h1(page)).toHaveText(workflow.name)
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
    const started = await runsOf(api, workflow.id)
    await expect(h1(page)).toBeVisible()
    await shotTo(page, 2, 'p9-run-now.png')
    save(2, 'p9-run-now.json', { workflow, url: page.url(), runId, started })
    expect(started.map((run) => run.run_id), 'the page opened the one run Run now started').toEqual([runId])
    expect(started[0]?.started_by).toBe('alice')
    assertClean(watch)
    await context.close()
  })
})

async function slowAnswers(page: Page, pattern: string, method: string, ms: number): Promise<void> {
  await page.route(pattern, async (route) => {
    if (route.request().method() !== method) return route.continue()
    await new Promise((resolve) => setTimeout(resolve, ms))
    await route.continue()
  })
}

test('@lane3 quick presses of Run now, and a press after a lost answer, start one run with one key', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (_backend, api) => {
    await connectMockModel(api)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const posts: { url: string; key: string | undefined; status: number | null }[] = []
    page.on('requestfinished', async (req) => {
      if (req.method() === 'POST' && req.url().endsWith('/runs')) posts.push({ url: req.url(), key: req.headers()['idempotency-key'], status: (await req.response())?.status() ?? null })
    })
    page.on('requestfailed', (req) => {
      if (req.method() === 'POST' && req.url().endsWith('/runs')) posts.push({ url: req.url(), key: req.headers()['idempotency-key'], status: null })
    })
    const results: Record<string, { posts: typeof posts; runsStarted: number }> = {}
    for (const how of ['two presses in one tick', 'a double click', 'two clicks 250 ms apart', 'Enter twice']) {
      const workflow = await agentWorkflow(api, `lane3 ${how.split(' ').slice(0, 2).join(' ')}`)
      await page.unrouteAll()
      await slowAnswers(page, `**/api/v1/use-cases/${workflow.id}/runs`, 'POST', 1_500)
      await page.goto(`/workflows/${workflow.id}`)
      await expect(h1(page)).toHaveText(workflow.name)
      posts.length = 0
      const button = page.getByRole('button', { name: 'Run now' })
      if (how === 'two presses in one tick') {
        await button.evaluate((element: HTMLElement) => {
          element.click()
          element.click()
        })
      } else if (how === 'a double click') {
        await button.dblclick()
      } else if (how === 'Enter twice') {
        await button.focus()
        await page.keyboard.press('Enter')
        await page.keyboard.press('Enter')
      } else {
        await button.click()
        await page.waitForTimeout(250)
        await button.click({ force: true })
      }
      await expect(page).toHaveURL(/\/runs\/[^/]+$/, { timeout: 15_000 })
      await page.waitForTimeout(500)
      results[how] = { posts: [...posts], runsStarted: (await runsOf(api, workflow.id)).length }
    }

    const lostAnswer = await agentWorkflow(api, 'lane3 lost answer')
    await page.unrouteAll()
    posts.length = 0
    await page.goto(`/workflows/${lostAnswer.id}`)
    await expect(h1(page)).toHaveText(lostAnswer.name)
    let lost = false
    await page.route(`**/api/v1/use-cases/${lostAnswer.id}/runs`, async (route) => {
      if (lost) return route.continue()
      lost = true
      await route.fetch()
      await route.abort('failed')
    })
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    await page.waitForTimeout(500)
    const afterLost = { posts: [...posts], runsStarted: (await runsOf(api, lostAnswer.id)).length, opened: new URL(page.url()).pathname }

    save(3, 'p9-run-now-twice.json', { presses: results, afterLost })
    for (const [how, result] of Object.entries(results)) {
      expect(result.posts, `${how}: one request`).toHaveLength(1)
      expect(result.runsStarted, `${how}: one run`).toBe(1)
    }
    expect(afterLost.posts.map((post) => post.key), 'the press after a lost answer sends the same key').toEqual([afterLost.posts[0]?.key, afterLost.posts[0]?.key])
    expect(afterLost.posts[1]?.status, 'the platform answers the repeated key with the run it started').toBe(200)
    expect(afterLost.runsStarted, 'a lost answer and a second press start one run').toBe(1)
    await context.close()
  })
})

test('@lane4 pausing a scheduled workflow makes its next run read Paused, and resuming shows a date again', async ({ browser }) => {
  const workflow = workflowSavedBySetup(4, 'scripts/checks/p9.sh lane4')
  await withBackend(async (_backend, api) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${workflow.id}`)
    await expect(h1(page)).toHaveText(workflow.name)
    await expect(nextRunOf(page)).toHaveText(DATE)
    const seen: Record<string, unknown> = { workflow, before: { next: await nextRunOf(page).innerText(), when: await whenOf(page).innerText() } }
    await page.getByRole('button', { name: 'Pause' }).click()
    await expect(nextRunOf(page)).toHaveText('Paused')
    seen['paused'] = { next: await nextRunOf(page).innerText(), when: await whenOf(page).innerText(), api: await useCaseOf(api, workflow.id) }
    await shotTo(page, 4, 'p9-pause.png')
    await expect(page.getByRole('button', { name: 'Resume' }), 'focus stays on the control').toBeFocused()
    await page.getByRole('button', { name: 'Resume' }).click()
    await expect(nextRunOf(page)).toHaveText(DATE)
    seen['resumed'] = { next: await nextRunOf(page).innerText(), when: await whenOf(page).innerText(), api: await useCaseOf(api, workflow.id) }
    await shotTo(page, 4, 'p9-resumed.png')
    save(4, 'p9-pause.json', seen)
    expect((seen['before'] as { when: string }).when).toContain('On a schedule')
    expect((seen['paused'] as { api: UseCase }).api.next_run_at).toBeNull()
    expect((seen['resumed'] as { api: UseCase }).api.next_run_at).not.toBeNull()
    assertClean(watch)
    await context.close()
  })
})

test('@lane5 a deleted workflow comes back with its past runs after Undo, which has no time limit', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (backend, api) => {
    const workflow = await workflowWithARun(backend, api, 'lane5 undo')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${workflow.id}`)
    await expect(h1(page)).toHaveText(workflow.name)
    await page.getByRole('button', { name: 'Delete' }).click()
    const dialog = page.getByRole('alertdialog', { name: `Delete ${workflow.name}?` })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Delete workflow' }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    await expect(rowOf(page, workflow.id)).toHaveCount(0)
    const whileDeleted = { listed: Boolean(await useCaseOf(api, workflow.id)), runs: (await runsOf(api, workflow.id)).map((run) => run.run_id) }
    const undo = page.getByRole('button', { name: 'Undo' })
    await expect(undo).toBeFocused()
    await page.mouse.move(5, 5)
    await page.locator('#find-workflows').focus()
    await page.waitForTimeout(LONGEST_PLAIN_TOAST_MS + 2_000)
    await expect(undo, 'Undo outlasts the longest plain message with focus and the pointer elsewhere').toBeVisible()
    await undo.click()
    await expect(rowOf(page, workflow.id)).toBeVisible()
    await expect(rowOf(page, workflow.id).locator('h2 + p')).not.toHaveText('No runs yet.')
    await expect(toastCard(page)).toHaveText('Put back.')
    await shotTo(page, 5, 'p9-undo-delete.png')
    await rowOf(page, workflow.id).getByRole('link', { name: workflow.name }).click()
    await expect(recentRuns(page).locator(`a[href="/runs/${workflow.runId}"]`)).toBeVisible()
    await shotTo(page, 5, 'p9-undo-delete-page.png')
    save(5, 'p9-undo-delete.json', { workflow, whileDeleted, after: { listed: await useCaseOf(api, workflow.id), runs: (await runsOf(api, workflow.id)).map((run) => run.run_id) } })
    expect(whileDeleted.listed, 'it left the list while deleted').toBe(false)
    expect(whileDeleted.runs, 'its runs stayed readable while deleted').toContain(workflow.runId)
    assertClean(watch)
    await context.close()
  })
})

test('@lane6 bob sees who may approve and the recent runs, has no manage buttons, and every write route refuses him', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (backend, api) => {
    const workflow = await workflowWithARun(backend, api, 'lane6 approver')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/workflows')
    await expect(rowOf(page, workflow.id)).toBeVisible()
    const listButtons = (await mainButtons(page)).filter((label) => MANAGE.includes(label))
    await page.goto(`/workflows/${workflow.id}`)
    await expect(h1(page)).toHaveText(workflow.name)
    await expect(page.getByRole('main')).toContainText(WHO_APPROVES)
    await expect(recentRuns(page).locator(`a[href="/runs/${workflow.runId}"]`)).toBeVisible()
    const buttons = await mainButtons(page)
    await shotTo(page, 6, 'p9-approver-view.png', true)
    save(6, 'p9-approver-view.json', { workflow, listButtons, buttons, main: await page.getByRole('main').innerText() })
    expect(listButtons, 'no manage buttons on the list').toEqual([])
    expect(buttons.filter((label) => MANAGE.includes(label)), 'no manage buttons on the page').toEqual([])

    const runsBefore = (await runsOf(api, workflow.id)).length
    const refused = {
      runNow: await call(api, 'bob', 'POST', `/api/v1/use-cases/${workflow.id}/runs`, undefined, { 'Idempotency-Key': randomUUID() }),
      pause: await call(api, 'bob', 'POST', `/api/v1/use-cases/${workflow.id}/pause`),
      resume: await call(api, 'bob', 'POST', `/api/v1/use-cases/${workflow.id}/resume`),
      delete: await call(api, 'bob', 'DELETE', `/api/v1/use-cases/${workflow.id}`),
      restore: { status: 0, body: null as unknown },
    }
    expect((await call(api, 'alice', 'DELETE', `/api/v1/use-cases/${workflow.id}`)).status, 'alice deletes it so bob can try to put it back').toBe(200)
    refused.restore = await call(api, 'bob', 'POST', `/api/v1/use-cases/${workflow.id}/restore`)
    const stillDeleted = (await call(api, 'alice', 'GET', `/api/v1/use-cases/${workflow.id}`)).status
    expect((await call(api, 'alice', 'POST', `/api/v1/use-cases/${workflow.id}/restore`)).status).toBe(200)
    const after = { state: (await useCaseOf(api, workflow.id))?.state, runsAdded: (await runsOf(api, workflow.id)).length - runsBefore }
    save(6, 'p9-approver-api.json', { refused, stillDeleted, after })
    for (const [what, answer] of Object.entries(refused)) expect(answer.status, `bob ${what}`).toBe(403)
    expect((refused.runNow.body as { detail: string }).detail, 'the refusal uses the app’s words').not.toMatch(RETIRED)
    expect(stillDeleted, 'bob could not put it back').toBe(404)
    expect(after).toEqual({ state: 'on', runsAdded: 0 })
    assertClean(watch)
    await context.close()
  })
})

test('@lane7 an agent’s name on the workflow page opens its card, and Close comes back', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    const workflow = await agentWorkflow(api, 'lane7 agent link')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${workflow.id}`)
    await expect(h1(page)).toHaveText(workflow.name)
    await page.getByRole('main').getByRole('link', { name: 'Version checker' }).click()
    const dialog = page.locator('main dialog[open]')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Version checker', level: 2 })).toBeVisible()
    await expect(page).toHaveURL(/\/agents\/crd_version_checker$/)
    await shotTo(page, 7, 'p9-agent-link.png')
    await dialog.getByRole('button', { name: 'Close' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/workflows/${workflow.id}$`))
    save(7, 'p9-agent-link.json', { workflow, backTo: page.url() })
    assertClean(watch)
    await context.close()
  })
})

test('@lane8-setup connect the mock model and make the workflow whose run will stop', async () => {
  await withBackend(async (_backend, api) => {
    await connectMockModel(api)
    const workflow = await agentWorkflow(api, 'lane8 stopped')
    save(8, 'workflow.json', workflow)
  })
})

test('@lane8 a workflow whose last run stopped says Stopped, in the list and on its page, and links to that run', async ({ browser }) => {
  test.setTimeout(300_000)
  const workflow = workflowSavedBySetup(8, 'scripts/checks/p9.sh lane8')
  await withBackend(async (backend) => {
    const runId = await backend.checkNow('alice', workflow.id)
    const run = await backend.waitForState(runId, ['failed'], 180_000)
    const facts: Record<string, unknown> = { workflow, runId, reason: run.reason }
    for (const user of ['alice', 'bob']) {
      const context = await devContext(browser, user)
      const page = await context.newPage()
      const watch = watchPage(page)
      await page.goto('/workflows')
      const row = rowOf(page, workflow.id)
      await expect(row).toBeVisible()
      facts[`${user} row`] = { text: await row.innerText(), links: await row.getByRole('link').evaluateAll((links) => links.map((link) => [link.textContent?.trim(), link.getAttribute('href')])) }
      await page.getByRole('button', { name: 'Stopped', exact: true }).click()
      facts[`${user} Stopped filter keeps it`] = await row.isVisible()
      await shotTo(page, 8, `p9-stopped-list-${user}.png`, true)
      await page.goto(`/workflows/${workflow.id}`)
      await expect(h1(page)).toHaveText(workflow.name)
      await expect(page.locator('[data-tone="bad"]')).toHaveText('Stopped')
      facts[`${user} page head`] = await page.getByRole('main').getByRole('link', { name: /See why it stopped|Review and decide/ }).evaluateAll((links) => links.map((link) => [link.textContent?.trim(), link.getAttribute('href')]))
      const latest = recentRuns(page).locator('li').first()
      await expect(latest).toHaveAttribute('data-run-id', runId)
      await expect(latest).toContainText('Stopped.')
      await expect(latest.getByRole('link')).toHaveAttribute('href', `/runs/${runId}`)
      if (user === 'alice') {
        await shotTo(page, 8, 'p9-stopped-latest.png')
        await latest.getByRole('link').click()
        await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
        facts['opened'] = page.url()
      }
      assertClean(watch)
      await context.close()
    }
    save(8, 'p9-stopped-latest.json', facts)
    const alice = facts['alice row'] as { text: string; links: [string, string][] }
    expect(alice.text).toContain('Stopped')
    expect(alice.text).toMatch(/Today \d{1,2}:\d{2}: stopped\./)
    expect(alice.links).toContainEqual(['See why it stopped', `/runs/${runId}`])
    expect(facts['alice Stopped filter keeps it']).toBe(true)
    expect(facts['alice page head']).toEqual([['See why it stopped', `/runs/${runId}`]])
    expect((facts['bob row'] as { text: string }).text).toContain('Stopped')
    expect(facts['bob page head'], 'an Approver gets no See why it stopped').toEqual([])
  })
})

async function axeOn(page: Page, view: string, width: string, runs: Record<string, unknown>[]): Promise<void> {
  await page.waitForTimeout(800)
  const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  runs.push({
    view,
    width,
    sideways,
    violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
    incomplete: result.incomplete.map((v) => ({ id: v.id, nodes: v.nodes.length })),
    passes: result.passes.length,
  })
}

test('@lane9 axe finds no WCAG 2.2 AA problem on either page, in each state, at 1440 and 390 px', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (backend, api) => {
    const workflow = await workflowWithARun(backend, api, 'lane9 axe')
    const runs: Record<string, unknown>[] = []
    for (const [width, phone] of [
      ['1440', false],
      ['390', true],
    ] as const) {
      const alice = await devContext(browser, 'alice', { phone })
      const page = await alice.newPage()
      await page.goto('/workflows')
      await expect(rowOf(page, workflow.id)).toBeVisible()
      await axeOn(page, 'list', width, runs)
      await page.locator('#find-workflows').fill('zzzz nothing')
      await expect(page.getByText('No workflows match')).toBeVisible()
      await axeOn(page, 'list, no match', width, runs)
      await page.route('**/api/v1/use-cases', (route) => (route.request().method() === 'GET' ? route.fulfill({ json: { use_cases: [] } }) : route.continue()))
      await page.goto('/workflows')
      await expect(page.getByText('No workflows yet')).toBeVisible()
      await axeOn(page, 'list, empty', width, runs)
      await page.unrouteAll()
      await page.goto(`/workflows/${workflow.id}`)
      await expect(h1(page)).toHaveText(workflow.name)
      await axeOn(page, 'workflow page', width, runs)
      await page.getByRole('button', { name: 'Pause' }).click()
      await expect(nextRunOf(page)).toHaveText('Paused')
      await axeOn(page, 'workflow page, paused, with its message', width, runs)
      await page.getByRole('button', { name: 'Resume' }).click()
      await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
      await page.getByRole('button', { name: 'Delete' }).click()
      await expect(page.getByRole('alertdialog')).toBeVisible()
      await axeOn(page, 'delete dialog', width, runs)
      await page.getByRole('alertdialog').getByRole('button', { name: 'Delete workflow' }).click()
      await expect(page.getByRole('button', { name: 'Undo' })).toBeVisible()
      await axeOn(page, 'list with the Undo message', width, runs)
      await page.getByRole('button', { name: 'Undo' }).click()
      await expect(rowOf(page, workflow.id)).toBeVisible()
      await page.goto('/workflows/uc_does_not_exist')
      await expect(h1(page)).toHaveText('Workflow not found')
      await axeOn(page, 'workflow not found', width, runs)
      await alice.close()

      const bob = await devContext(browser, 'bob', { phone })
      const bobPage = await bob.newPage()
      await bobPage.goto('/workflows')
      await expect(rowOf(bobPage, workflow.id)).toBeVisible()
      await axeOn(bobPage, 'bob, list', width, runs)
      await bobPage.goto(`/workflows/${workflow.id}`)
      await expect(h1(bobPage)).toHaveText(workflow.name)
      await axeOn(bobPage, 'bob, workflow page', width, runs)
      await bob.close()
    }
    save(9, 'p9-axe.json', { tags: WCAG_22_AA, runs })
    expect(runs.flatMap((run) => (run['violations'] as { id: string }[]).map((v) => `${String(run['view'])} @${String(run['width'])}: ${v.id}`))).toEqual([])
    expect(runs.filter((run) => (run['sideways'] as number) > 0).map((run) => `${String(run['view'])} @${String(run['width'])}`), 'no sideways scroll').toEqual([])
  })
})

async function clickRowInView(page: Page): Promise<{ name: string; atClick: number }> {
  await page.evaluate(() => {
    const w = window as unknown as { __atClick: number | null }
    w.__atClick = null
    document.addEventListener('click', () => (w.__atClick = window.scrollY), { capture: true, once: true })
  })
  const links = page.locator('li[data-workflow-id] h2 a').filter({ hasText: /lane10/ })
  const viewport = page.viewportSize() ?? { width: 1440, height: 900 }
  for (let i = 0; i < (await links.count()); i++) {
    const box = await links.nth(i).boundingBox()
    if (!box || box.y < 160 || box.y + box.height > viewport.height - 200) continue
    const x = box.x + Math.min(20, box.width / 2)
    const y = box.y + box.height / 2
    const hit = await page.evaluate(([px, py]) => document.elementFromPoint(px, py)?.closest('a')?.textContent ?? null, [x, y] as const)
    if (!hit) continue
    await page.mouse.click(x, y)
    return { name: hit.trim(), atClick: await page.evaluate(() => (window as unknown as { __atClick: number | null }).__atClick ?? -1) }
  }
  throw new Error('no lane10 row link is fully in view')
}

test('@lane10 Back and the back control return the list where it was, at 1440 and 390 px', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (_backend, api) => {
    for (let i = 0; i < 14; i++) await agentWorkflow(api, `lane10 ${String(i).padStart(2, '0')}`)
    const rows: Record<string, unknown>[] = []
    for (const phone of [false, true]) {
      const width = phone ? '390' : '1440'
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      for (const how of ['browser Back', 'back control'] as const) {
        await page.goto('/workflows')
        await expect(page.locator('li[data-workflow-id]').nth(13)).toBeVisible()
        await page.waitForTimeout(600)
        await page.evaluate(() => window.scrollTo(0, 900))
        await page.waitForTimeout(300)
        const scrolled = await page.evaluate(() => window.scrollY)
        const { name, atClick } = await clickRowInView(page)
        await expect(h1(page)).toHaveText(name)
        const onPage = await page.evaluate(() => window.scrollY)
        if (how === 'browser Back') await page.goBack()
        else await page.getByRole('main').getByRole('link', { name: 'Workflows', exact: true }).click()
        await expect(h1(page)).toHaveText('Workflows')
        await page.waitForTimeout(600)
        const after = await page.evaluate(() => window.scrollY)
        await shotTo(page, 10, `p9-back-${width}-${how.replaceAll(' ', '-').toLowerCase()}.png`)
        rows.push({ width, how, scrolled, atClick, opened: name, onPage, after, url: page.url() })
      }
      await context.close()
    }
    save(10, 'p9-back.json', rows)
    for (const row of rows) {
      const label = `${String(row['width'])} px, ${String(row['how'])}`
      expect(row['scrolled'] as number, `${label}: the list was scrolled`).toBeGreaterThan(100)
      expect(row['atClick'], `${label}: the click did not move the page`).toBe(row['scrolled'])
      expect(row['onPage'], `${label}: the workflow page opens at its top`).toBe(0)
      expect(Math.abs((row['after'] as number) - (row['atClick'] as number)), `${label}: the list comes back where it was`).toBeLessThanOrEqual(2)
    }
  })
})

async function focusNow(page: Page): Promise<{ tag: string | null; text: string }> {
  return page.evaluate(() => ({ tag: document.activeElement?.tagName ?? null, text: (document.activeElement?.textContent ?? '').trim().slice(0, 40) }))
}

test('@focus every page change puts focus on the new heading, with nothing cached', async ({ browser }) => {
  test.setTimeout(300_000)
  const rows: Record<string, unknown>[] = []
  for (const from of ['/settings', '/', '/agents']) {
    for (let attempt = 1; attempt <= 3; attempt++) {
      const context = await devContext(browser, 'alice')
      const page = await context.newPage()
      await page.goto(from)
      await expect(h1(page)).toBeVisible()
      await page.waitForTimeout(500)
      await mainMenu(page).getByRole('link', { name: 'Workflows', exact: true }).click()
      await expect(h1(page)).toHaveText('Workflows')
      await page.waitForTimeout(1_200)
      rows.push({ from, to: '/workflows', attempt, ...(await focusNow(page)) })
      await page.locator('li[data-workflow-id] h2 a[href^="/workflows/"]').first().click()
      await expect(page.getByRole('main').getByRole('link', { name: 'Workflows', exact: true })).toBeVisible()
      await page.waitForTimeout(1_200)
      rows.push({ from: '/workflows', to: 'a workflow page', attempt, ...(await focusNow(page)) })
      await page.goBack()
      await expect(h1(page)).toHaveText('Workflows')
      await page.waitForTimeout(1_200)
      rows.push({ from: 'a workflow page', to: '/workflows, by Back', attempt, ...(await focusNow(page)) })
      await context.close()
    }
  }
  save('probe-focus', `focus-${TARGET}.json`, rows)
  expect(rows.filter((row) => row['tag'] !== 'H1').map((row) => `${String(row['from'])} -> ${String(row['to'])} #${String(row['attempt'])}: ${String(row['tag'])}`), 'focus is on the new heading after every page change').toEqual([])
})

test('@stale Run now on a page that still shows On after someone else paused it shows the paused workflow', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    await connectMockModel(api)
    const workflow = await agentWorkflow(api, 'stale run now')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto(`/workflows/${workflow.id}`)
    await expect(page.getByRole('button', { name: 'Run now' })).toBeVisible()
    expect((await call(api, 'carol', 'POST', `/api/v1/use-cases/${workflow.id}/pause`)).status, 'carol pauses it').toBe(200)
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page.getByRole('alert')).toContainText('paused')
    await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
    await expect(nextRunOf(page)).toHaveText('Paused')
    const facts = { workflow, alert: await page.getByRole('alert').allInnerTexts(), url: page.url(), buttons: await mainButtons(page), pills: await page.locator('[data-life]').innerText() }
    await shotTo(page, 'safety', 'stale-run-now.png')
    save('safety', 'stale-run-now.json', facts)
    expect(facts.buttons).not.toContain('Run now')
    expect(facts.pills).toBe('Paused')
    expect(await runsOf(api, workflow.id)).toEqual([])
    await context.close()
  })
})

test('@watchlist the watchlist row and address open the Software page, and the Workflows pages offer no manage control for it', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const watchlist = await backend.freshWatchlist('alice')
    const facts: Record<string, unknown> = { watchlist }
    for (const user of ['alice', 'carol', 'bob']) {
      const context = await devContext(browser, user)
      const page = await context.newPage()
      await page.goto('/workflows')
      const row = rowOf(page, watchlist)
      await expect(row).toBeVisible()
      facts[`${user} row link`] = await row.locator('h2 a').getAttribute('href')
      facts[`${user} row controls`] = (await row.getByRole('button').allInnerTexts()).concat(await row.getByRole('link').allInnerTexts()).filter((label) => MANAGE.includes(label.trim()))
      await row.locator('h2 a').click()
      await expect(page).toHaveURL(/\/software$/)
      await page.goto(`/workflows/${watchlist}`)
      await expect(page).toHaveURL(/\/software$/)
      facts[`${user} address lands on`] = new URL(page.url()).pathname
      facts[`${user} heading`] = await h1(page).innerText()
      await context.close()
    }
    const platform = await call(api, 'alice', 'DELETE', `/api/v1/use-cases/${watchlist}`)
    facts['platform delete'] = platform
    save('safety', 'watchlist.json', facts)
    for (const user of ['alice', 'carol', 'bob']) {
      expect(facts[`${user} row link`]).toBe('/software')
      expect(facts[`${user} row controls`]).toEqual([])
      expect(facts[`${user} address lands on`]).toBe('/software')
    }
    expect(platform.status, 'the platform keeps the watchlist').toBe(409)
  })
})

test('@roles only an Operator sees Run now, Pause, Resume and Delete', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    const on = await agentWorkflow(api, 'roles on')
    const paused = await agentWorkflow(api, 'roles paused')
    expect((await call(api, 'alice', 'POST', `/api/v1/use-cases/${paused.id}/pause`)).status).toBe(200)
    const seen: Record<string, Record<string, string[]>> = {}
    for (const user of ['alice', 'carol', 'bob']) {
      const context = await devContext(browser, user)
      const page = await context.newPage()
      seen[user] = {}
      for (const [label, workflow] of [
        ['on', on],
        ['paused', paused],
      ] as const) {
        await page.goto(`/workflows/${workflow.id}`)
        await expect(page.getByText('Who approves')).toBeVisible()
        await page.waitForTimeout(300)
        seen[user][label] = (await mainButtons(page)).filter((b) => MANAGE.includes(b))
        if (label === 'paused') await shotTo(page, 'safety', `roles-${user}-paused.png`, true)
      }
      await context.close()
    }
    save('safety', 'roles.json', seen)
    for (const operator of ['alice', 'carol']) {
      expect(seen[operator]?.['on'], `${operator} on an On workflow`).toEqual(['Run now', 'Pause', 'Delete'])
      expect(seen[operator]?.['paused'], `${operator} on a paused workflow`).toEqual(['Resume', 'Delete'])
    }
    expect(seen['bob']).toEqual({ on: [], paused: [] })
  })
})

async function decideShown(browser: Browser, user: string, id: string): Promise<{ list: number; page: number }> {
  const context = await devContext(browser, user)
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(rowOf(page, id)).toBeVisible()
  const list = await rowOf(page, id).getByRole('link', { name: 'Review and decide' }).count()
  await page.goto(`/workflows/${id}`)
  await expect(page.getByText('Who approves')).toBeVisible()
  await expect(recentRuns(page).getByRole('link').first()).toBeVisible()
  const onPage = await page.getByRole('main').getByRole('link', { name: 'Review and decide' }).count()
  await context.close()
  return { list, page: onPage }
}

test('@own-run Review and decide never shows for a run the viewer started or a workflow the viewer owns', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (backend, api) => {
    await connectMockModel(api)
    const cases: Record<string, unknown>[] = []
    const byCarol = await agentWorkflow(api, 'carol owns', 'carol')
    const r1 = await backend.checkNow('carol', byCarol.id)
    await backend.waitForState(r1, ['awaiting_approval'], 180_000)
    cases.push({ case: 'carol owns, carol started', alice: await decideShown(browser, 'alice', byCarol.id), bob: await decideShown(browser, 'bob', byCarol.id), carol: await decideShown(browser, 'carol', byCarol.id) })
    const r2 = await backend.checkNow('alice', byCarol.id)
    await backend.waitForState(r2, ['awaiting_approval'], 180_000)
    cases.push({ case: 'carol owns, alice started', alice: await decideShown(browser, 'alice', byCarol.id), bob: await decideShown(browser, 'bob', byCarol.id) })
    const byAlice = await agentWorkflow(api, 'alice owns')
    const r3 = await backend.checkNow('carol', byAlice.id)
    await backend.waitForState(r3, ['awaiting_approval'], 180_000)
    cases.push({ case: 'alice owns, carol started', alice: await decideShown(browser, 'alice', byAlice.id), bob: await decideShown(browser, 'bob', byAlice.id) })
    const platform: Record<string, unknown> = {}
    for (const [label, runId] of [
      ['alice started it', r2],
      ['alice owns it', r3],
    ] as const) {
      const approvalId = await backend.approvalIdOf(runId)
      const approval = (await call(api, 'alice', 'GET', `/api/v1/approvals/${approvalId}`)).body as { digest?: string; steps?: { index: number }[]; why_not?: unknown }
      platform[label] = { why_not: approval.why_not, decide: await call(api, 'alice', 'POST', `/api/v1/approvals/${approvalId}/decisions`, { step: approval.steps?.[0]?.index ?? 0, verdict: 'approve', digest: approval.digest ?? '' }) }
    }
    save('safety', 'own-run.json', { cases, platform })
    const at = (i: number, who: string) => (cases[i] as Record<string, { list: number; page: number }>)[who]
    expect(at(0, 'alice'), 'control: alice may decide a run carol started on carol’s workflow').toEqual({ list: 1, page: 1 })
    expect(at(0, 'bob')).toEqual({ list: 1, page: 1 })
    expect(at(0, 'carol'), 'carol is not an Approver').toEqual({ list: 0, page: 0 })
    expect(at(1, 'alice'), 'alice started the latest run').toEqual({ list: 0, page: 0 })
    expect(at(1, 'bob')).toEqual({ list: 1, page: 1 })
    expect(at(2, 'alice'), 'alice owns the workflow').toEqual({ list: 0, page: 0 })
    expect(at(2, 'bob')).toEqual({ list: 1, page: 1 })
    for (const answer of Object.values(platform) as { decide: { status: number; body: { message?: string } } }[]) {
      expect(answer.decide.status).toBe(403)
      expect(answer.decide.body.message, 'the refusal is true for the person who started it and for the owner').toBe('This run is your own work, so another Approver must decide.')
    }
  })
})

test('@delete-undo Delete asks first, Cancel and Escape keep it, and Undo puts it back as it was', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (backend, api) => {
    const workflow = await workflowWithARun(backend, api, 'delete undo')
    expect((await call(api, 'alice', 'POST', `/api/v1/use-cases/${workflow.id}/pause`)).status).toBe(200)
    const before = (await call(api, 'alice', 'GET', `/api/v1/use-cases/${workflow.id}`)).body as Record<string, unknown>
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const deletes: string[] = []
    page.on('request', (r: Request) => {
      if (r.method() === 'DELETE' && r.url().includes(`/use-cases/${workflow.id}`)) deletes.push(r.url())
    })
    const status = async () => (await call(api, 'alice', 'GET', `/api/v1/use-cases/${workflow.id}`)).status
    await page.goto(`/workflows/${workflow.id}`)
    await expect(h1(page)).toHaveText(workflow.name)
    const dialog = page.getByRole('alertdialog', { name: `Delete ${workflow.name}?` })
    const steps: Record<string, unknown>[] = []
    await page.getByRole('button', { name: 'Delete' }).click()
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
    steps.push({ step: 'Delete pressed', dialog: await dialog.innerText(), deletes: deletes.length })
    await shotTo(page, 'safety', 'delete-asks.png')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Delete' })).toBeFocused()
    steps.push({ step: 'Escape', deletes: deletes.length, status: await status() })
    await page.getByRole('button', { name: 'Delete' }).click()
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toHaveCount(0)
    steps.push({ step: 'Cancel', deletes: deletes.length, status: await status() })
    await page.getByRole('button', { name: 'Delete' }).click()
    await dialog.getByRole('button', { name: 'Delete workflow' }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    await expect(rowOf(page, workflow.id)).toHaveCount(0)
    steps.push({ step: 'Delete workflow', deletes: deletes.length, status: await status(), toast: await toastCard(page).innerText() })
    await shotTo(page, 'safety', 'delete-toast.png')
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(rowOf(page, workflow.id)).toBeVisible()
    await page.waitForTimeout(400)
    const toastAfter = await toastCard(page).innerText().catch(() => '')
    const rowText = await rowOf(page, workflow.id).innerText()
    await shotTo(page, 'safety', 'delete-undone.png')
    const after = (await call(api, 'alice', 'GET', `/api/v1/use-cases/${workflow.id}`)).body as Record<string, unknown>
    const runs = (await runsOf(api, workflow.id)).map((run) => run.run_id)
    const differs = Object.keys({ ...before, ...after }).filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    save('safety', 'delete-undo.json', { workflow, steps, toastAfter, rowText, before, after, differs, runs })
    expect(steps.map((step) => step['deletes'])).toEqual([0, 0, 0, 1])
    expect(steps[1]?.['status']).toBe(200)
    expect(steps[2]?.['status']).toBe(200)
    expect(steps[3]?.['status'], 'it is gone while deleted').toBe(404)
    expect(steps[3]?.['toast']).toContain(`Deleted ${workflow.name}.`)
    expect(toastAfter).toBe('Put back.')
    expect(differs, 'Undo puts it back exactly as it was').toEqual([])
    expect(rowText).toContain('Paused')
    expect(runs).toContain(workflow.runId)
    await context.close()
  })
})

async function setHidden(page: Page, hidden: boolean): Promise<void> {
  await page.evaluate((h) => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => h })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (h ? 'hidden' : 'visible') })
    document.dispatchEvent(new Event('visibilitychange'))
  }, hidden)
}

async function goneAfter(page: Page, startedAt: number, limitMs: number): Promise<number | null> {
  const deadline = Date.now() + limitMs
  while (Date.now() < deadline) {
    if ((await toastCard(page).count()) === 0) return Date.now() - startedAt
    await page.waitForTimeout(100)
  }
  return null
}

test('@toast the Undo message has no time limit; a plain message waits on hover and a hidden tab', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (_backend, api) => {
    const result: Record<string, unknown> = {}
    const toggled = await agentWorkflow(api, 'toast pause')
    const deleted = await agentWorkflow(api, 'toast undo')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto(`/workflows/${toggled.id}`)
    await expect(h1(page)).toHaveText(toggled.name)
    await page.mouse.move(5, 5)
    await page.getByRole('button', { name: 'Pause' }).click()
    await expect(toastCard(page)).toBeVisible()
    result['plainText'] = await toastCard(page).innerText()
    let t0 = Date.now()
    result['plainAlone_ms'] = await goneAfter(page, t0, 15_000)

    await page.getByRole('button', { name: 'Resume' }).click()
    await expect(toastCard(page)).toBeVisible()
    await toastCard(page).hover()
    await page.waitForTimeout(LONGEST_PLAIN_TOAST_MS + 4_000)
    result['plainHovered_visibleAfter14s'] = await toastCard(page).isVisible()
    await page.mouse.move(5, 5)
    t0 = Date.now()
    result['plainAfterPointerLeaves_ms'] = await goneAfter(page, t0, 10_000)

    await page.getByRole('button', { name: 'Pause' }).click()
    await expect(toastCard(page)).toBeVisible()
    await setHidden(page, true)
    await page.waitForTimeout(LONGEST_PLAIN_TOAST_MS + 4_000)
    result['plainHidden_visibleAfter14s'] = await toastCard(page).isVisible()
    await setHidden(page, false)
    t0 = Date.now()
    result['plainAfterTabShows_ms'] = await goneAfter(page, t0, 10_000)

    await page.goto(`/workflows/${deleted.id}`)
    await expect(h1(page)).toHaveText(deleted.name)
    await page.getByRole('button', { name: 'Delete' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Delete workflow' }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    await expect(page.getByRole('button', { name: 'Undo' })).toBeFocused()
    await page.mouse.move(5, 5)
    await page.locator('#find-workflows').focus()
    await page.waitForTimeout(25_000)
    result['undoVisibleAfter25s_focusElsewhere'] = await page.getByRole('button', { name: 'Undo' }).isVisible()
    await setHidden(page, true)
    await page.waitForTimeout(10_000)
    await setHidden(page, false)
    await page.waitForTimeout(8_000)
    result['undoVisibleAfterHiddenAndShown'] = await page.getByRole('button', { name: 'Undo' }).isVisible()
    await shotTo(page, 'safety', 'toast-undo-after-43s.png')
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(rowOf(page, deleted.id)).toBeVisible()
    result['afterUndo'] = await toastCard(page).innerText().catch(() => '')
    await context.close()
    save('safety', 'toast.json', result)
    expect(result['plainAlone_ms'], 'a plain message leaves by itself').not.toBeNull()
    expect(result['plainHovered_visibleAfter14s'], 'hover holds a plain message').toBe(true)
    expect(result['plainAfterPointerLeaves_ms'], 'and it leaves after the pointer goes').not.toBeNull()
    expect(result['plainHidden_visibleAfter14s'], 'a hidden tab holds a plain message').toBe(true)
    expect(result['plainAfterTabShows_ms'], 'and it leaves once the tab shows').not.toBeNull()
    expect(result['undoVisibleAfter25s_focusElsewhere'], 'Undo has no time limit').toBe(true)
    expect(result['undoVisibleAfterHiddenAndShown']).toBe(true)
    expect(result['afterUndo']).toBe('Put back.')
  })
})

async function animationsNow(page: Page): Promise<{ name: string; state: string; on: string }[]> {
  return page.evaluate(() =>
    document.getAnimations().map((a) => {
      const target = (a.effect as KeyframeEffect | null)?.target as Element | null
      return { name: (a as CSSAnimation).animationName ?? a.constructor.name, state: a.playState, on: target ? `${target.tagName.toLowerCase()}.${String(target.className).slice(0, 40)}` : '?' }
    }),
  )
}

test('@reduced reduced motion stops the animation on the list, the page, the dialog and the message', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (_backend, api) => {
    const workflow = await agentWorkflow(api, 'motion')
    const result: Record<string, Record<string, unknown>> = {}
    for (const reducedMotion of [false, true]) {
      const context = await devContext(browser, 'alice', { reducedMotion })
      const page = await context.newPage()
      await page.goto('/')
      await expect(h1(page)).toBeVisible()
      await mainMenu(page).getByRole('link', { name: 'Workflows', exact: true }).click()
      await expect(rowOf(page, workflow.id)).toBeVisible()
      const list = await animationsNow(page)
      const rowAnimation = await rowOf(page, workflow.id).evaluate((element) => getComputedStyle(element).animationName)
      await page.goto(`/workflows/${workflow.id}`)
      await expect(h1(page)).toHaveText(workflow.name)
      await page.waitForTimeout(400)
      const pageIdle = await animationsNow(page)
      await page.getByRole('button', { name: 'Pause' }).click()
      await expect(nextRunOf(page)).toHaveText('Paused')
      const afterPause = await animationsNow(page)
      const tintAnimation = await nextRunOf(page).locator('span').evaluate((element) => getComputedStyle(element).animationName)
      await page.waitForTimeout(LONGEST_PLAIN_TOAST_MS + 2_000)
      const toastLeftByItself = (await toastCard(page).count()) === 0
      await page.getByRole('button', { name: 'Resume' }).click()
      await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
      await page.getByRole('button', { name: 'Delete' }).click()
      await expect(page.getByRole('alertdialog')).toBeVisible()
      const dialog = await animationsNow(page)
      await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel' }).click()
      result[reducedMotion ? 'reduce' : 'normal'] = { list, rowAnimation, pageIdle, afterPause, tintAnimation, toastLeftByItself, dialog }
      await context.close()
    }
    save('safety', 'reduced-motion.json', result)
    const { reduce = {}, normal = {} } = result
    expect((normal['list'] as unknown[]).length + (normal['afterPause'] as unknown[]).length + (normal['dialog'] as unknown[]).length, 'normal motion animates (control)').toBeGreaterThan(0)
    for (const key of ['list', 'pageIdle', 'afterPause', 'dialog']) expect(reduce[key], `reduced motion: ${key}`).toEqual([])
    expect(reduce['rowAnimation']).toBe('none')
    expect(reduce['tintAnimation']).toBe('none')
    expect(reduce['toastLeftByItself'], 'a plain message still leaves under reduced motion').toBe(true)
  })
})

test('@words the Workflows pages use no retired name in their own words, apart from what people named and wrote', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    await agentWorkflow(api, 'words')
    const typedByPeople = (await listedWorkflows(api)).flatMap((item) => [item.name, item.instruction])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const hits: Record<string, string[]> = {}
    const text = async () =>
      `${await page.locator('body').innerText()} ${await page.evaluate(() => [...document.querySelectorAll('[aria-label],[title],[placeholder],[alt]')].map((e) => ['aria-label', 'title', 'placeholder', 'alt'].map((a) => e.getAttribute(a) ?? '').join(' ')).join(' '))} ${await page.title()}`
    const scan = (where: string, all: string) => {
      const words = typedByPeople.filter(Boolean).reduce((left, typed) => left.replaceAll(typed, ' '), all)
      const found = [...words.matchAll(new RegExp(RETIRED, 'gi'))].map((m) => m[0])
      if (found.length) hits[where] = found
    }
    await page.goto('/workflows')
    await expect(page.locator('li[data-workflow-id]').first()).toBeVisible()
    scan('/workflows', await text())
    const links = await page.locator('li[data-workflow-id] h2 a[href^="/workflows/"]').evaluateAll((elements) => elements.map((e) => e.getAttribute('href') ?? ''))
    for (const href of links.slice(0, 8)) {
      await page.goto(href)
      await expect(page.getByText('Who approves')).toBeVisible()
      await page.waitForTimeout(300)
      scan(href, await text())
    }
    save('safety', 'words.json', { pagesScanned: Math.min(links.length, 8) + 1, hits })
    await context.close()
    expect(hits).toEqual({})
  })
})

async function findOrMakePerfWorkflowWithRuns(backend: Backend, api: APIRequestContext, count: number): Promise<Workflow> {
  await connectMockModel(api)
  const known = (await listedWorkflows(api)).find((item) => item.name === PERF_WORKFLOW)
  let workflow: Workflow
  if (known) workflow = { id: known.use_case_id, name: known.name }
  else {
    const made = await call(api, 'alice', 'POST', '/api/v1/agent-use-cases', { name: PERF_WORKFLOW, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [VERSION_CHECKER] })
    expect(made.status, `alice makes ${PERF_WORKFLOW}`).toBe(201)
    workflow = { id: (made.body as { use_case_id: string }).use_case_id, name: PERF_WORKFLOW }
  }
  const have = (await runsOf(api, workflow.id)).length
  for (let i = have; i < count; i++) await backend.waitForState(await backend.checkNow('alice', workflow.id), SETTLED, 180_000)
  return workflow
}

test('@perf largest contentful paint of a workflow page with 20 recent runs, and when the run list is drawn', async ({ browser }) => {
  test.setTimeout(900_000)
  const workflow = await withBackend((backend, api) => findOrMakePerfWorkflowWithRuns(backend, api, 20))
  const context = await devContext(browser, 'alice')
  await context.addInitScript(() => {
    const w = window as unknown as { __runsDrawnAt: number | null }
    w.__runsDrawnAt = null
    const seen = () => {
      if (w.__runsDrawnAt !== null) return
      const heading = [...document.querySelectorAll('section h2')].find((h) => h.textContent === 'Recent runs')
      if (heading?.parentElement?.querySelector('li a')) w.__runsDrawnAt = performance.now()
    }
    new MutationObserver(seen).observe(document, { childList: true, subtree: true })
  })
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`, { waitUntil: 'load' })
  await expect(h1(page)).toHaveText(workflow.name)
  await expect(recentRuns(page).getByRole('link').first()).toBeVisible()
  await page.waitForTimeout(1_500)
  const measured = await page.evaluate(
    () =>
      new Promise<{ entries: { startTime: number; element: string }[] }>((resolve) => {
        const entries: { startTime: number; element: string }[] = []
        const observer = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as (PerformanceEntry & { element: Element | null })[]) {
            entries.push({ startTime: e.startTime, element: e.element ? `${e.element.tagName.toLowerCase()} "${(e.element.textContent ?? '').trim().slice(0, 40)}"` : 'gone' })
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => {
          observer.disconnect()
          resolve({ entries })
        }, 500)
      }),
  )
  const runsDrawnAt = await page.evaluate(() => (window as unknown as { __runsDrawnAt: number | null }).__runsDrawnAt)
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  expect(runsDrawnAt, 'the run list was drawn').not.toBeNull()
  const shown = await recentRuns(page).getByRole('link').count()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, useCaseId: workflow.id, runsShown: shown, lcp: last?.startTime ?? -1, runsDrawnAt: runsDrawnAt ?? -1, element: last?.element ?? '', entries: measured.entries })
  await context.close()
})

async function reviewVideo(browser: Browser): Promise<void> {
  await withBackend(async (backend, api) => {
    const workflow = await workflowWithARun(backend, api, 'review')
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
      locale: 'en-SG',
      timezoneId: 'Asia/Singapore',
    })
    await context.addInitScript(() => window.localStorage.setItem('portal.dev-user', 'alice'))
    const page = await context.newPage()
    const video = page.video()
    await page.goto('/workflows')
    await expect(rowOf(page, workflow.id)).toBeVisible()
    await page.waitForTimeout(4_000)
    await rowOf(page, workflow.id).getByRole('link', { name: workflow.name }).hover()
    await page.waitForTimeout(1_000)
    await rowOf(page, workflow.id).getByRole('link', { name: workflow.name }).click()
    await expect(h1(page)).toHaveText(workflow.name)
    await page.waitForTimeout(4_000)
    await page.getByRole('button', { name: 'Pause' }).click()
    await page.waitForTimeout(3_000)
    await page.getByRole('button', { name: 'Resume' }).click()
    await page.waitForTimeout(3_000)
    await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }))
    await page.waitForTimeout(3_500)
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    await page.waitForTimeout(2_500)
    await page.getByRole('button', { name: 'Run now' }).hover()
    await page.waitForTimeout(1_000)
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page).toHaveURL(/\/runs\//)
    await page.waitForTimeout(12_000)
    await context.close()
    await video?.saveAs(path.join(EVID, 'p9-review.webm'))
  })
}

test('@review-video the list, a workflow page, Pause and Resume, and Run now', async ({ browser }) => {
  test.setTimeout(400_000)
  await reviewVideo(browser)
})
