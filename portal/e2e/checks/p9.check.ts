import AxeBuilder from '@axe-core/playwright'
import { expect, request, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { Backend, setMockGithubMode } from '../live/support/stack'
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

interface UseCase {
  use_case_id: string
  name: string
  state: 'on' | 'paused'
  next_run_at: string | null
}

interface Run {
  run_id: string
  use_case_id: string
  state: string
  started_by: string
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = false): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })
const rowOf = (page: Page, useCaseId: string) => page.locator(`li[data-workflow-id="${useCaseId}"]`)
const nextRunOf = (page: Page) => page.locator('dt', { hasText: 'Next run' }).locator('xpath=following-sibling::dd[1]')
const recentRuns = (page: Page) => page.getByRole('region', { name: 'Recent runs' })

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

async function call(api: APIRequestContext, user: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', url: string, data?: unknown): Promise<{ status: number; body: unknown }> {
  const response = await api.fetch(url, { method, headers: { 'X-Dev-User': user }, ...(data === undefined ? {} : { data }) })
  const text = await response.text()
  return { status: response.status(), body: text ? (JSON.parse(text) as unknown) : null }
}

async function useCaseOf(api: APIRequestContext, id: string): Promise<UseCase | undefined> {
  const { body } = await call(api, 'alice', 'GET', '/api/v1/use-cases')
  return (body as { use_cases: UseCase[] }).use_cases.find((item) => item.use_case_id === id)
}

async function runsOf(api: APIRequestContext, id: string): Promise<Run[]> {
  const { body } = await call(api, 'alice', 'GET', '/api/v1/runs')
  return (body as { runs: Run[] }).runs.filter((run) => run.use_case_id === id)
}

async function scheduledWatchlist(backend: Backend, api: APIRequestContext): Promise<string> {
  const id = await backend.freshWatchlist('alice')
  await call(api, 'alice', 'POST', `/api/v1/use-cases/${id}/resume`)
  const saved = await call(api, 'alice', 'PUT', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
  expect(saved.status, 'the watchlist schedule saves').toBe(200)
  return id
}

async function agentWorkflow(api: APIRequestContext, label: string): Promise<{ id: string; name: string }> {
  const name = `p9 ${label} ${randomUUID().slice(0, 6)}`
  const made = await call(api, 'alice', 'POST', '/api/v1/agent-use-cases', { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [VERSION_CHECKER] })
  expect(made.status, `alice makes ${name}`).toBe(201)
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

test('@lane1 each row shows On or Paused and its latest run as separate facts', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const watchlist = await scheduledWatchlist(backend, api)
    await backend.checkNow('alice', watchlist)
    const paused = await agentWorkflow(api, 'lane1 paused')
    expect((await call(api, 'alice', 'POST', `/api/v1/use-cases/${paused.id}/pause`)).status).toBe(200)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/workflows')
    await expect(h1(page)).toHaveText('Workflows')
    await expect(page.getByRole('main')).not.toContainText(NOT_BUILT)
    const facts: Record<string, unknown>[] = []
    for (const id of [watchlist, paused.id]) {
      const row = rowOf(page, id)
      await expect(row).toBeVisible()
      const life = row.locator('[data-life]')
      const line = row.locator('h2 + p')
      facts.push({ id, life: await life.innerText(), lifeState: await life.getAttribute('data-life'), latest: await line.innerText(), next: await row.innerText() })
      await expect(life).toHaveText(/^(On|Paused)$/)
      await expect(line, 'the latest run is its own line, apart from the pill').not.toHaveText(/^(On|Paused)$/)
    }
    await expect(rowOf(page, watchlist).locator('[data-life]')).toHaveText('On')
    await expect(rowOf(page, watchlist).locator('h2 + p')).not.toHaveText('No runs yet.')
    await expect(rowOf(page, paused.id).locator('[data-life]')).toHaveText('Paused')
    await expect(rowOf(page, paused.id)).toContainText('Next: Paused')
    await shotTo(page, 1, 'p9-list.png', true)
    save(1, 'p9-list.json', { target: TARGET, facts })
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 alice presses Run now and the run page opens on the new run', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    const before = (await runsOf(api, id)).map((run) => run.run_id)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${id}`)
    await expect(h1(page)).toHaveText('Software watchlist')
    await page.getByRole('button', { name: 'Run now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
    const after = await runsOf(api, id)
    const started = after.filter((run) => !before.includes(run.run_id))
    await expect(h1(page)).toBeVisible()
    await shotTo(page, 2, 'p9-run-now.png')
    save(2, 'p9-run-now.json', { url: page.url(), runId, started })
    expect(started.map((run) => run.run_id), 'the page opened the one run Run now started').toEqual([runId])
    expect(started[0]?.started_by).toBe('alice')
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 two quick presses of Run now, and a press after a lost answer, start one run with one key', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const posts: { key: string | undefined; status: number | null }[] = []
    page.on('requestfinished', async (req) => {
      if (req.method() === 'POST' && req.url().endsWith(`/use-cases/${id}/runs`)) posts.push({ key: req.headers()['idempotency-key'], status: (await req.response())?.status() ?? null })
    })
    page.on('requestfailed', (req) => {
      if (req.method() === 'POST' && req.url().endsWith(`/use-cases/${id}/runs`)) posts.push({ key: req.headers()['idempotency-key'], status: null })
    })

    const before = (await runsOf(api, id)).length
    await page.goto(`/workflows/${id}`)
    await expect(h1(page)).toHaveText('Software watchlist')
    await page.getByRole('button', { name: 'Run now' }).evaluate((button: HTMLElement) => {
      button.click()
      button.click()
    })
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    await page.waitForTimeout(500)
    const twice = { posts: [...posts], runsStarted: (await runsOf(api, id)).length - before }

    posts.length = 0
    const beforeLost = (await runsOf(api, id)).length
    await page.goto(`/workflows/${id}`)
    await expect(h1(page)).toHaveText('Software watchlist')
    let lost = false
    await page.route(`**/api/v1/use-cases/${id}/runs`, async (route) => {
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
    const afterLost = { posts: [...posts], runsStarted: (await runsOf(api, id)).length - beforeLost, opened: new URL(page.url()).pathname }

    save(3, 'p9-run-now-twice.json', { twice, afterLost })
    expect(twice.posts, 'two presses in one tick send one request').toHaveLength(1)
    expect(twice.runsStarted, 'two presses in one tick start one run').toBe(1)
    expect(afterLost.posts.map((p) => p.key), 'the press after a lost answer sends the same key').toEqual([afterLost.posts[0]?.key, afterLost.posts[0]?.key])
    expect(afterLost.posts[1]?.status, 'the platform answers the repeated key with the run it started').toBe(200)
    expect(afterLost.runsStarted, 'a lost answer and a second press start one run').toBe(1)
    await context.close()
  })
})

test('@lane4 pausing makes the next run read Paused, and resuming shows a date again', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${id}`)
    await expect(h1(page)).toHaveText('Software watchlist')
    const seen: Record<string, string> = { before: await nextRunOf(page).innerText() }
    await page.getByRole('button', { name: 'Pause' }).click()
    await expect(nextRunOf(page)).toHaveText('Paused')
    seen['paused'] = await nextRunOf(page).innerText()
    seen['api_paused'] = JSON.stringify(await useCaseOf(api, id))
    await shotTo(page, 4, 'p9-pause.png')
    await expect(page.getByRole('button', { name: 'Resume' }), 'focus stays on the control').toBeFocused()
    await page.getByRole('button', { name: 'Resume' }).click()
    await expect(nextRunOf(page)).toHaveText(DATE)
    seen['resumed'] = await nextRunOf(page).innerText()
    seen['api_resumed'] = JSON.stringify(await useCaseOf(api, id))
    await shotTo(page, 4, 'p9-resumed.png')
    save(4, 'p9-pause.json', seen)
    expect(seen['before']).toMatch(DATE)
    assertClean(watch)
    await context.close()
  })
})

test('@lane5 a deleted workflow comes back with its past runs after Undo', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    await connectMockModel(api)
    const workflow = await agentWorkflow(api, 'lane5 undo')
    const runId = await backend.checkNow('alice', workflow.id)
    await backend.waitForState(runId, SETTLED)
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
    await page.waitForTimeout(6_000)
    await expect(undo, 'Undo has no time limit').toBeVisible()
    await undo.click()
    await expect(rowOf(page, workflow.id)).toBeVisible()
    await expect(rowOf(page, workflow.id).locator('h2 + p')).not.toHaveText('No runs yet.')
    await shotTo(page, 5, 'p9-undo-delete.png')
    await rowOf(page, workflow.id).getByRole('link', { name: workflow.name }).click()
    await expect(recentRuns(page).locator(`a[href="/runs/${runId}"]`)).toBeVisible()
    await shotTo(page, 5, 'p9-undo-delete-page.png')
    save(5, 'p9-undo-delete.json', { workflow, runId, whileDeleted, after: { listed: await useCaseOf(api, workflow.id), runs: (await runsOf(api, workflow.id)).map((run) => run.run_id) } })
    expect(whileDeleted.listed, 'it left the list while deleted').toBe(false)
    expect(whileDeleted.runs, 'its runs stayed readable while deleted').toContain(runId)
    assertClean(watch)
    await context.close()
  })
})

test('@lane6 bob sees who may approve and the recent runs, but no manage buttons', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    const runId = await backend.checkNow('alice', id)
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${id}`)
    await expect(h1(page)).toHaveText('Software watchlist')
    await expect(page.getByRole('main')).toContainText(WHO_APPROVES)
    await expect(recentRuns(page).locator(`a[href="/runs/${runId}"]`)).toBeVisible()
    const buttons = await page.getByRole('main').getByRole('button').allInnerTexts()
    await shotTo(page, 6, 'p9-approver-view.png', true)
    save(6, 'p9-approver-view.json', { buttons, main: await page.getByRole('main').innerText() })
    expect(buttons.filter((label) => MANAGE.includes(label.trim())), 'no manage buttons for an Approver').toEqual([])
    const refused = await call(api, 'bob', 'POST', `/api/v1/use-cases/${id}/pause`)
    save(6, 'p9-approver-api.json', refused)
    expect(refused.status, 'the platform refuses bob too').toBe(403)
    assertClean(watch)
    await context.close()
  })
})

test('@lane7 an agent’s name on the workflow page opens its card, and Close comes back', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${id}`)
    await expect(h1(page)).toHaveText('Software watchlist')
    await page.getByRole('main').getByRole('link', { name: 'Version checker' }).click()
    const dialog = page.locator('main dialog[open]')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Version checker', level: 2 })).toBeVisible()
    await expect(page).toHaveURL(/\/agents\/crd_version_checker$/)
    await shotTo(page, 7, 'p9-agent-link.png')
    await dialog.getByRole('button', { name: 'Close' }).first().click()
    await expect(page).toHaveURL(new RegExp(`/workflows/${id}$`))
    save(7, 'p9-agent-link.json', { backTo: page.url() })
    assertClean(watch)
    await context.close()
  })
})

test('@lane8 a workflow whose last run stopped says Stopped and links to that run', async ({ browser }) => {
  await withBackend(async (backend) => {
    await setMockGithubMode('unavailable')
    try {
      const id = await backend.freshWatchlist('alice')
      const runId = await backend.checkNow('alice', id)
      await backend.waitForState(runId, ['failed'])
      const context = await devContext(browser, 'alice')
      const page = await context.newPage()
      const watch = watchPage(page)
      await page.goto(`/workflows/${id}`)
      await expect(h1(page)).toHaveText('Software watchlist')
      await expect(page.locator('[data-tone="bad"]')).toHaveText('Stopped')
      const latest = recentRuns(page).locator('li').first()
      await expect(latest).toHaveAttribute('data-run-id', runId)
      await expect(latest).toContainText('Stopped.')
      await expect(latest.getByRole('link')).toHaveAttribute('href', `/runs/${runId}`)
      await shotTo(page, 8, 'p9-stopped-latest.png')
      await latest.getByRole('link').click()
      await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
      save(8, 'p9-stopped-latest.json', { runId, opened: page.url() })
      assertClean(watch)
      await context.close()
    } finally {
      await setMockGithubMode('ok')
    }
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

test('@lane9 axe finds no WCAG 2.2 AA problem on both pages at 1440 and 390 px', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    await backend.checkNow('alice', id)
    const runs: Record<string, unknown>[] = []
    for (const [width, phone] of [
      ['1440', false],
      ['390', true],
    ] as const) {
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      await page.goto('/workflows')
      await expect(rowOf(page, id)).toBeVisible()
      await axeOn(page, 'list', width, runs)
      await page.goto(`/workflows/${id}`)
      await expect(h1(page)).toHaveText('Software watchlist')
      await axeOn(page, 'workflow page', width, runs)
      await page.getByRole('button', { name: 'Pause' }).click()
      await expect(nextRunOf(page)).toHaveText('Paused')
      await axeOn(page, 'workflow page, paused, with its message', width, runs)
      await page.getByRole('button', { name: 'Resume' }).click()
      await expect(nextRunOf(page)).toHaveText(DATE)
      await context.close()
    }
    save(9, 'p9-axe.json', { tags: WCAG_22_AA, runs })
    expect(runs.flatMap((run) => (run['violations'] as { id: string }[]).map((v) => `${String(run['view'])} @${String(run['width'])}: ${v.id}`))).toEqual([])
    expect(runs.filter((run) => (run['sideways'] as number) > 0).map((run) => `${String(run['view'])} @${String(run['width'])}`), 'no sideways scroll').toEqual([])
  })
})

test('@lane10 Back from a workflow returns the list at the same scroll position', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    for (let i = 0; i < 14; i++) await agentWorkflow(api, `lane10 ${String(i).padStart(2, '0')}`)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/workflows')
    await expect(page.locator('li[data-workflow-id]').nth(13)).toBeVisible()
    await page.evaluate(() => window.scrollTo(0, Math.min(700, document.documentElement.scrollHeight - window.innerHeight)))
    await page.waitForTimeout(300)
    const before = await page.evaluate(() => window.scrollY)
    const target = page.locator('li[data-workflow-id] h2 a').filter({ hasText: /lane10/ }).nth(6)
    const name = (await target.innerText()).trim()
    await target.click()
    await expect(h1(page)).toHaveText(name)
    const onPage = await page.evaluate(() => window.scrollY)
    await page.goBack()
    await expect(h1(page)).toHaveText('Workflows')
    await page.waitForTimeout(500)
    const after = await page.evaluate(() => window.scrollY)
    await shotTo(page, 10, 'p9-back.png')
    save(10, 'p9-back.json', { before, onPage, after, opened: name })
    expect(before, 'the list was scrolled').toBeGreaterThan(100)
    expect(onPage, 'the workflow page opened at its top').toBe(0)
    expect(Math.abs(after - before), 'Back returns the list where it was').toBeLessThanOrEqual(2)
    await context.close()
  })
})

async function workflowWithRuns(backend: Backend, api: APIRequestContext, count: number): Promise<string> {
  const id = await scheduledWatchlist(backend, api)
  const have = (await runsOf(api, id)).length
  const started: string[] = []
  for (let i = have; i < count; i++) started.push(await backend.checkNow('alice', id))
  for (const runId of started) await backend.waitForState(runId, SETTLED, 180_000)
  return id
}

test('@perf largest contentful paint of a workflow page with 20 recent runs', async ({ browser }) => {
  test.setTimeout(600_000)
  const id = await withBackend((backend, api) => workflowWithRuns(backend, api, 20))
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${id}`, { waitUntil: 'load' })
  await expect(h1(page)).toHaveText('Software watchlist')
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
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  const shown = await recentRuns(page).getByRole('link').count()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, useCaseId: id, runsShown: shown, lcp: last?.startTime ?? -1, element: last?.element ?? '', entries: measured.entries })
  await context.close()
})

async function reviewVideo(browser: Browser): Promise<void> {
  await withBackend(async (backend, api) => {
    const id = await scheduledWatchlist(backend, api)
    await backend.checkNow('alice', id)
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
    await expect(rowOf(page, id)).toBeVisible()
    await page.waitForTimeout(4_000)
    await rowOf(page, id).getByRole('link', { name: 'Software watchlist' }).hover()
    await page.waitForTimeout(1_000)
    await rowOf(page, id).getByRole('link', { name: 'Software watchlist' }).click()
    await expect(h1(page)).toHaveText('Software watchlist')
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
  test.setTimeout(180_000)
  await reviewVideo(browser)
})
