/**
 * The checker's checks for P6's live lanes and perf block (docs/design/rebuild-plan.md): the Software watchlist page.
 * Run through scripts/checks/p6.sh, which picks the stack and the lane with --grep @laneN.
 * Evidence goes to $EVID/lane-<n>/ with the file names the plan gives.
 */
import { expect, request, test, type Locator, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { Backend, LANGGRAPH, MOCK_GITHUB_URL, REDIS, setMockGithubMode, type Software } from '../live/support/stack'
import { devContext } from '../live/support/ui'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p6'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const UNDO_STAYS_MS = 10_000
const VIDEO_SECONDS = { min: 30, max: 60 }

interface Row {
  id: string
  name: string
  status: string
  problem: string | null
  our_version: string | null
  newest_version: string | null
  newest_read_at: string | null
  checked_at: string | null
  our_version_source: { kind: string; ticket: string | null } | null
  open_ticket: string | null
  added_by: string
  added_at: string
  source: { ref: string }
}

interface View {
  use_case_id: string
  state: 'on' | 'paused'
  software: Row[]
  last_check: { run_id: string; state: string; started_at: string } | null
  schedule: { day: string; at: string; owner: string; owner_name: string; next_at: string | null } | null
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function shotTo(page: Page, lane: number, name: string, fullPage = false): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

async function withBackend<T>(act: (backend: Backend) => Promise<T>): Promise<T> {
  const backend = await Backend.connect(BASE_URL)
  try {
    return await act(backend)
  } finally {
    await backend.dispose()
  }
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })
const notice = (page: Page) => page.locator('div[class*="notice"] > p[role="status"]')
const problem = (page: Page) => page.locator('#change-problem')
const rowOf = (page: Page, name: string): Locator => page.locator('li[data-status]').filter({ has: page.locator('b', { hasText: new RegExp(`^${name}$`) }) })
const text = async (locator: Locator) => ((await locator.innerText()) || '').replace(/\s+/g, ' ').trim()

async function viewOf(backend: Backend, user = 'alice'): Promise<View> {
  return (await backend.get<{ watchlist: View }>(user, '/api/v1/watchlist')).watchlist
}

async function rowNamed(backend: Backend, name: string): Promise<Row> {
  const row = (await viewOf(backend)).software.find((item) => item.name === name)
  expect(row, `${name} is on the watchlist`).toBeDefined()
  return row as Row
}

async function openSoftware(page: Page): Promise<void> {
  await page.goto('/software')
  await expect(h1(page)).toHaveText('Software watchlist')
  await expect(page.getByText('Loading the software list')).toHaveCount(0)
  await expect(notice(page), 'the list has loaded: the lazy page draws its notice line with it').toBeAttached()
}

async function addInForm(page: Page, software: Software): Promise<void> {
  await page.getByLabel('Name', { exact: true }).fill(software.name)
  await page.getByLabel('GitHub repository').fill(software.repo)
  await page.getByLabel(/^Our version/).fill(software.our_version)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
}

async function newestOnMockGithub(repo: string): Promise<{ status: number; newest: string }> {
  const http = await request.newContext()
  try {
    const answer = await http.get(`${MOCK_GITHUB_URL}/repos/${repo}/releases?per_page=100`)
    const tags = ((await answer.json()) as { tag_name: string }[]).map((release) => release.tag_name).filter((tag) => /^\d+\.\d+\.\d+$/.test(tag))
    const parts = (tag: string) => tag.split('.').map(Number)
    const newer = (a: string, b: string) => {
      const [x, y] = [parts(a), parts(b)]
      const at = x.findIndex((n, i) => n !== y[i])
      return at >= 0 && (x[at] ?? 0) > (y[at] ?? 0)
    }
    return { status: answer.status(), newest: tags.reduce((best, tag) => (newer(tag, best) ? tag : best), '0.0.0') }
  } finally {
    await http.dispose()
  }
}

function manyRows(count: number): Software[] {
  return Array.from({ length: count }, (_, index) => {
    const n = String(index + 1).padStart(2, '0')
    return { name: `Tool ${n}`, repo: `acme/tool-${n}`, our_version: '1.0.0' }
  })
}

test('@lane1-trunk trunk has no Software watchlist page', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/software')
  await expect(h1(page)).toBeVisible()
  const body = await text(page.getByRole('main'))
  save(1, 'p6-trunk.json', { target: 'trunk', url: page.url(), body })
  expect(body).toContain('This page is not built yet.')
  await context.close()
})

test('@lane1 alice adds software, presses Check now, lands on the run, and the row shows the newest version and a ticket waiting for a yes; two presses in one tick send once', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [])
    const runsBefore = (await backend.runs()).length
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const keys: string[] = []
    const adds: string[] = []
    page.on('request', (request) => {
      if (request.method() !== 'POST') return
      if (/\/use-cases\/[^/]+\/runs$/.test(request.url())) keys.push(request.headers()['idempotency-key'] ?? '')
      if (new URL(request.url()).pathname === '/api/v1/watchlist/software') adds.push(request.postData() ?? '')
    })
    const pressTwiceInOneTick = (button: Locator) =>
      button.evaluate((element: HTMLButtonElement) => {
        element.click()
        element.click()
      })
    await openSoftware(page)
    await expect(page.getByText('No software yet')).toBeVisible()
    await page.getByLabel('Name', { exact: true }).fill(LANGGRAPH.name)
    await page.getByLabel('GitHub repository').fill(LANGGRAPH.repo)
    await page.getByLabel(/^Our version/).fill(LANGGRAPH.our_version)
    await pressTwiceInOneTick(page.getByRole('button', { name: 'Add', exact: true }))
    await expect(rowOf(page, 'LangGraph')).toBeVisible()
    await expect(rowOf(page, 'LangGraph')).toContainText('Not checked yet')
    await expect(page.locator('#sw-repo-error')).toHaveCount(0)
    await pressTwiceInOneTick(page.getByRole('button', { name: 'Check now' }))
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = page.url().split('/').at(-1) ?? ''
    await backend.waitForState(runId, ['awaiting_approval'])
    const runsStarted = (await backend.runs()).length - runsBefore
    await openSoftware(page)
    const row = rowOf(page, 'LangGraph')
    await expect(row).toContainText('Ticket waiting for a yes', { timeout: 30_000 })
    const api = await rowNamed(backend, 'LangGraph')
    const mock = await newestOnMockGithub(LANGGRAPH.repo)
    await expect(row.locator('dd').nth(1)).toHaveText(mock.newest)
    await shotTo(page, 1, 'p6-check.png', true)
    save(1, 'p6-check.json', { runId, idempotencyKeys: keys, adds, runsStarted, mock, row: api, rowOnPage: await text(row) })
    expect(mock.status, 'the mock GitHub serves LangGraph').toBe(200)
    expect(api.newest_version, 'the newest plain release the mock GitHub serves').toBe(mock.newest)
    expect(adds, 'two presses of Add sent one add').toHaveLength(1)
    expect(keys, 'two presses of Check now started one check with one key').toHaveLength(1)
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/)
    expect(runsStarted, 'the platform has one new run').toBe(1)
    expect(api.newest_version, 'the mock GitHub has a newer release').not.toBeNull()
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 a badly formed GitHub reference says what is wrong and saves nothing', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [REDIS])
    const before = await viewOf(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const posts: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && request.url().includes('/watchlist/software')) posts.push(request.url())
    })
    await openSoftware(page)
    const attempts = ['langgraph', 'https://example.com/a/b', 'a b/c']
    const said: string[] = []
    for (const bad of attempts) {
      await page.getByLabel('Name', { exact: true }).fill('Bad one')
      await page.getByLabel('GitHub repository').fill(bad)
      await page.getByRole('button', { name: 'Add', exact: true }).click()
      const field = page.getByLabel('GitHub repository')
      await expect(field).toHaveAttribute('aria-invalid', 'true')
      await expect(field).toBeFocused()
      await expect(page.locator('#sw-repo-error')).toContainText('That doesn’t look like a GitHub project')
      said.push(await text(page.locator('#sw-repo-error')))
    }
    await shotTo(page, 2, 'p6-bad-ref.png', true)
    const after = await viewOf(backend)
    save(2, 'p6-bad-ref.json', { attempts, said, posts, before: before.software.map((r) => r.name), after: after.software.map((r) => r.name) })
    expect(posts, 'nothing was sent').toEqual([])
    expect(after.software.map((r) => r.name)).toEqual(before.software.map((r) => r.name))

    for (const bad of ['acme/..', 'acme/.', 'https://github.com/acme/..']) {
      await page.getByLabel('GitHub repository').fill(bad)
      await page.getByRole('button', { name: 'Add', exact: true }).click()
      await expect(page.locator('#sw-repo-error')).toContainText('That doesn’t look like a GitHub project')
    }
    expect(posts, 'a dot name is refused in the page, as the platform refuses it').toEqual([])

    await addInForm(page, { name: 'Kafka', repo: 'apache/kafka', our_version: '3.9.0' })
    await expect(notice(page)).toHaveText('Added Kafka. Press Check now to check it.')
    await page.getByRole('button', { name: 'Dismiss' }).click()
    await expect(notice(page), 'Dismiss clears the message').toHaveText('')
    await expect(page.getByRole('searchbox', { name: 'Find software' })).toBeFocused()
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 Remove reaches the platform at once; Undo, with no time limit of its own, brings the same row back whole, also for another Operator; refusals read plainly', async ({ browser }) => {
  await withBackend(async (backend) => {
    const runId = await backend.startCheck('alice', [LANGGRAPH, REDIS])
    await backend.waitForState(runId, ['awaiting_approval'])
    const before = await rowNamed(backend, 'LangGraph')
    const redis = await rowNamed(backend, 'Redis')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const changes: string[] = []
    page.on('request', (request) => {
      const { pathname } = new URL(request.url())
      if (/\/watchlist\/software\/[^/]+(\/restore)?$/.test(pathname)) changes.push(`${request.method()} ${pathname}`)
    })
    await openSoftware(page)
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^Remove/ }).click()
    await expect(rowOf(page, 'LangGraph')).toHaveCount(0)
    await expect(notice(page)).toHaveText('Removed LangGraph. It won’t be checked any more.')
    const undo = page.getByRole('button', { name: 'Undo' })
    await expect(undo, 'focus moves to Undo').toBeFocused()
    const removed = (await viewOf(backend)).software.map((r) => r.name)
    await page.waitForTimeout(UNDO_STAYS_MS)
    await expect(undo, 'Undo has no time limit').toBeFocused()
    await page.keyboard.press('Enter')
    const row = rowOf(page, 'LangGraph')
    await expect(row).toBeVisible()
    await expect(notice(page)).toHaveText('Put LangGraph back on the list.')
    await expect(row.getByRole('button', { name: /^Remove/ }), 'focus returns to the row').toBeFocused()
    await expect(row).toContainText('Ticket waiting for a yes')
    await row.getByRole('button', { name: /^History/ }).click()
    const history = row.getByRole('list', { name: 'History of LangGraph' })
    await expect(history).toContainText('Checked. The newest version is')
    await expect(history).toContainText('Added by Alice.')
    const historyOnPage = await text(history)
    const kept = await rowNamed(backend, 'LangGraph')
    await shotTo(page, 3, 'p6-undo.png', true)

    await rowOf(page, 'Redis').getByRole('button', { name: /^Remove/ }).click()
    await expect(rowOf(page, 'Redis')).toHaveCount(0)
    await expect(undo).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(undo, 'Escape dismisses Undo').toHaveCount(0)
    const after = (await viewOf(backend)).software.map((r) => r.name)

    await backend.delete('carol', `/api/v1/watchlist/software/${before.id}`)
    const byCarol = await backend.send<{ software: Row[] }>('POST', 'carol', `/api/v1/watchlist/software/${before.id}/restore`)
    const backByCarol = byCarol.body.software.find((r) => r.id === before.id)
    const whileListed = await backend.send<View>('POST', 'alice', `/api/v1/watchlist/software/${before.id}/restore`)
    const neverListed = await backend.send('POST', 'alice', '/api/v1/watchlist/software/sw_01NEVERLISTED00000000000000/restore')

    await openSoftware(page)
    await backend.delete('carol', `/api/v1/watchlist/software/${before.id}`)
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^Remove/ }).click()
    await expect(notice(page)).toHaveText('LangGraph was already removed.')
    await expect(rowOf(page, 'LangGraph')).toHaveCount(0)
    const alertsAfterGone = await page.getByRole('alert').allInnerTexts()
    await expect(page.locator('#change-notice'), 'focus moves to the notice, as the row and its Remove button are gone').toBeFocused()
    await shotTo(page, 3, 'p6-gone.png', true)
    // Escape clears the notice wherever focus is on the page, as in the prototype, not only on its buttons.
    const find = page.getByRole('searchbox', { name: 'Find software' })
    await find.focus()
    await page.keyboard.press('Escape')
    await expect(notice(page), 'Escape from the search box clears the notice').toHaveText('')
    await expect(find, 'and leaves focus where it was').toBeFocused()

    await backend.post('alice', `/api/v1/watchlist/software/${redis.id}/restore`)
    await openSoftware(page)
    await rowOf(page, 'Redis').getByRole('button', { name: /^Remove/ }).click()
    await expect(undo).toBeFocused()
    const readded = await backend.post<{ software: Row[] }>('carol', '/api/v1/watchlist/software', REDIS, {}, [201])
    await undo.click()
    await expect(problem(page)).toHaveText('Could not put Redis back. Its repository was added again since, so it is on the list already.')
    await expect(problem(page), 'focus moves to the words').toBeFocused()
    await expect(undo, 'the refused Undo is gone').toHaveCount(0)
    await expect(notice(page)).toHaveText('')
    await expect(rowOf(page, 'Redis'), 'the list is read again at once, not at the next poll').toBeVisible({ timeout: 5_000 })
    const clash = await backend.send('POST', 'alice', `/api/v1/watchlist/software/${redis.id}/restore`)
    await shotTo(page, 3, 'p6-undo-refused.png', true)

    save(3, 'p6-undo.json', {
      before,
      kept,
      removed,
      after,
      changes,
      historyOnPage,
      byCarol: { status: byCarol.status, row: backByCarol },
      whileListed: whileListed.status,
      neverListed,
      alertsAfterGone,
      readded: readded.software.find((r) => r.name === 'Redis')?.id,
      clash,
    })
    expect(removed, 'the platform dropped LangGraph before Undo').toEqual(['Redis'])
    expect(kept, 'the same row comes back whole: id, who added it and when, the version given, status and newest').toEqual(before)
    expect(after).toEqual(['LangGraph'])
    expect(changes.slice(0, 3)).toEqual([
      `DELETE /api/v1/watchlist/software/${before.id}`,
      `POST /api/v1/watchlist/software/${before.id}/restore`,
      `DELETE /api/v1/watchlist/software/${redis.id}`,
    ])
    expect(byCarol.status).toBe(200)
    expect(backByCarol, 'a restore by another Operator keeps who added it').toEqual(before)
    expect(whileListed.status, 'restoring a listed row changes nothing').toBe(200)
    expect(neverListed).toEqual({ status: 404, body: { detail: 'This software was never on the watchlist' } })
    expect(alertsAfterGone, 'a row someone else removed is not an error').toEqual([])
    expect(clash.status, 'a repository added again since cannot be restored').toBe(409)
    assertClean(watch)
    await context.close()
  })
})

test('@lane3-day Undo more than a day after the removal is refused in plain words; p6.sh lane 3 moves the removal back a day while the page waits', async ({ browser }) => {
  const ids = process.env['LATE_REMOVAL_IDS'] ?? ''
  const moved = process.env['LATE_REMOVAL_MOVED'] ?? ''
  test.skip(ids === '' || moved === '', 'p6.sh lane 3 runs this, as it moves the removal back a day')
  rmSync(ids, { force: true })
  await withBackend(async (backend) => {
    const useCaseId = await backend.freshWatchlist('alice', [LANGGRAPH, REDIS])
    const langgraph = await rowNamed(backend, 'LangGraph')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^Remove/ }).click()
    const undo = page.getByRole('button', { name: 'Undo' })
    await expect(undo).toBeFocused()
    writeFileSync(ids, `use_case_id=${useCaseId}\nsoftware_id=${langgraph.id}\n`)
    await expect.poll(() => existsSync(moved), { message: 'p6.sh lane 3 moves the removal back a day', timeout: 90_000, intervals: [500] }).toBe(true)
    await undo.click()
    await expect(problem(page)).toHaveText('Could not put LangGraph back. It was removed more than a day ago. Add it again to keep checking it.')
    await expect(problem(page)).toBeFocused()
    await expect(undo).toHaveCount(0)
    await expect(rowOf(page, 'LangGraph')).toHaveCount(0)
    const late = await backend.send('POST', 'alice', `/api/v1/watchlist/software/${langgraph.id}/restore`)
    const listed = (await viewOf(backend)).software.map((r) => r.name)
    await shotTo(page, 3, 'p6-undo-late.png', true)
    save(3, 'p6-undo-late.json', { softwareId: langgraph.id, late, listed, onPage: await text(problem(page)) })
    expect(late).toEqual({ status: 410, body: { detail: 'This software was removed more than a day ago, so it can\'t be put back.' } })
    expect(listed).toEqual(['Redis'])
    assertClean(watch)
    await context.close()
  })
})

test('@lane3-near Undo just under a day after the removal still puts the row back; p6.sh lane 3 moves the removal back 23 hours while the page waits', async ({ browser }) => {
  const ids = process.env['LATE_REMOVAL_IDS'] ?? ''
  const moved = process.env['LATE_REMOVAL_MOVED'] ?? ''
  test.skip(ids === '' || moved === '', 'p6.sh lane 3 runs this, as it moves the removal back 23 hours')
  rmSync(ids, { force: true })
  await withBackend(async (backend) => {
    const useCaseId = await backend.freshWatchlist('alice', [LANGGRAPH, REDIS])
    const langgraph = await rowNamed(backend, 'LangGraph')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^Remove/ }).click()
    const undo = page.getByRole('button', { name: 'Undo' })
    await expect(undo).toBeFocused()
    writeFileSync(ids, `use_case_id=${useCaseId}\nsoftware_id=${langgraph.id}\n`)
    await expect.poll(() => existsSync(moved), { message: 'p6.sh lane 3 moves the removal back 23 hours', timeout: 90_000, intervals: [500] }).toBe(true)
    await undo.click()
    const row = rowOf(page, 'LangGraph')
    await expect(notice(page)).toHaveText('Put LangGraph back on the list.')
    await expect(row).toBeVisible()
    await expect(row.getByRole('button', { name: /^Remove/ }), 'focus returns to the row').toBeFocused()
    const listed = (await viewOf(backend)).software.map((r) => r.name)
    await shotTo(page, 3, 'p6-undo-near.png', true)
    save(3, 'p6-undo-near.json', { softwareId: langgraph.id, listed, onPage: await text(notice(page)) })
    expect(listed).toEqual(expect.arrayContaining(['LangGraph', 'Redis']))
    assertClean(watch)
    await context.close()
  })
})

test('@lane4 carol sets the schedule to every Monday at 9:00, warned that she becomes its owner, and the page shows the next check in Singapore time with carol as owner', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [LANGGRAPH])
    const context = await devContext(browser, 'carol')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await page.getByRole('button', { name: 'Set a schedule' }).click()
    await expect(page.getByLabel('Day'), 'focus moves into the editor').toBeFocused()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('button', { name: 'Set a schedule' }), 'Cancel returns focus to the button that opened the editor').toBeFocused()
    await page.getByRole('button', { name: 'Set a schedule' }).click()
    await expect(page.getByLabel('Day')).toBeFocused()
    const warning = 'Saving makes you the owner of this schedule. Its checks then count as your work, so you won’t be able to approve them.'
    await expect(page.getByText(warning)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save schedule' })).toHaveAccessibleDescription(warning)
    await page.getByLabel('Day').selectOption('monday')
    await page.getByLabel('Time, Singapore').fill('09:00')
    await page.getByRole('button', { name: 'Save schedule' }).click()
    await expect(page.getByText('Checked every Monday at 9:00, set by Carol.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Change schedule' }), 'focus returns to the button that opened the editor').toBeFocused()
    const api = (await viewOf(backend)).schedule
    const parts = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Singapore' }).formatToParts(new Date(api?.next_at ?? ''))
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
    const expected = `${get('weekday')} ${get('day')} ${get('month')}, ${Number(get('hour'))}:${get('minute')}`
    await expect(page.getByText(`Next check ${expected}, Singapore time.`)).toBeVisible()
    await expect(page.getByText('Carol can’t approve them')).toBeVisible()
    await shotTo(page, 4, 'p6-schedule.png', true)
    save(4, 'p6-schedule.json', { schedule: api, expected, onPage: await text(page.locator('section[aria-labelledby="schedule-heading"]')) })
    expect(api?.owner).toBe('carol')
    expect(api?.day).toBe('monday')
    assertClean(watch)
    await context.close()
  })
})

test('@lane5 bob, an Approver only, sees the list and no add, remove, schedule or check controls, and the platform refuses each of his writes', async ({ browser }) => {
  await withBackend(async (backend) => {
    const useCaseId = await backend.freshWatchlist('alice', [LANGGRAPH, REDIS])
    const lg = await rowNamed(backend, 'LangGraph')
    const gone = await rowNamed(backend, 'Redis')
    await backend.delete('alice', `/api/v1/watchlist/software/${gone.id}`)
    const writes: Record<string, number> = {
      'POST add': (await backend.send('POST', 'bob', '/api/v1/watchlist/software', { name: 'Nope', repo: 'acme/nope' })).status,
      'DELETE remove': (await backend.send('DELETE', 'bob', `/api/v1/watchlist/software/${lg.id}`)).status,
      'POST restore': (await backend.send('POST', 'bob', `/api/v1/watchlist/software/${gone.id}/restore`)).status,
      'PUT schedule': (await backend.send('PUT', 'bob', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })).status,
      'DELETE schedule': (await backend.send('DELETE', 'bob', '/api/v1/watchlist/schedule')).status,
      'POST run (Check now)': (await backend.send('POST', 'bob', `/api/v1/use-cases/${useCaseId}/runs`, undefined, { 'Idempotency-Key': randomUUID() })).status,
      'POST pause': (await backend.send('POST', 'bob', `/api/v1/use-cases/${useCaseId}/pause`)).status,
      'POST resume': (await backend.send('POST', 'bob', `/api/v1/use-cases/${useCaseId}/resume`)).status,
    }
    const left = await viewOf(backend)
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await expect(rowOf(page, 'LangGraph')).toBeVisible()
    const names = await page.getByRole('button').allInnerTexts()
    const controls = names.filter((name) => /^(Check now|Remove|Change schedule|Set a schedule|Turn off schedule|Add)\b/.test(name.trim()))
    await shotTo(page, 5, 'p6-approver-view.png', true)
    save(5, 'p6-approver-view.json', { buttons: names, controls, writes, left: { names: left.software.map((r) => r.name), state: left.state, schedule: left.schedule } })
    expect(controls).toEqual([])
    await expect(page.getByRole('heading', { name: 'Add software' })).toHaveCount(0)
    await expect(page.getByLabel('GitHub repository')).toHaveCount(0)
    for (const [write, status] of Object.entries(writes)) expect(status, `the platform refuses bob: ${write}`).toBe(403)
    expect(left.software.map((r) => r.name)).toEqual(['LangGraph'])
    expect(left.state).toBe('on')
    expect(left.schedule).toBeNull()
    assertClean(watch)
    await context.close()
  })
})

test('@lane6 when the mock GitHub fails during a check of rows that were Up to date, each row says it can’t check with its own reason, keeps the newest version it last read, and will try at the next check', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (backend) => {
    const useCaseId = await backend.freshWatchlist('alice', [
      { ...LANGGRAPH, our_version: '1.2.16' },
      { ...REDIS, our_version: '8.2.1' },
    ])
    await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
    const first = await backend.checkNow('alice', useCaseId)
    await backend.waitForState(first, ['succeeded'])
    const before = await viewOf(backend)
    await setMockGithubMode('unavailable')
    let runId = ''
    try {
      runId = await backend.checkNow('alice', useCaseId)
      await backend.waitForState(runId, ['failed'], 150_000)
    } finally {
      await setMockGithubMode('ok')
    }
    const view = await viewOf(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    const onPage: Record<string, { row: string; history: string }> = {}
    for (const name of ['LangGraph', 'Redis']) {
      const was = before.software.find((r) => r.name === name)
      const now = view.software.find((r) => r.name === name)
      const row = rowOf(page, name)
      await expect(row).toHaveAttribute('data-status', 'cant_check')
      await expect(row).toContainText('Can’t check')
      await expect(row).toContainText(`${now?.problem ?? 'missing'} It will try again at the next check.`)
      await expect(row.locator('dd').nth(1)).toContainText(was?.newest_version ?? 'missing')
      await expect(row.getByText(/^Last read /)).toBeVisible()
      await row.getByRole('button', { name: /^History/ }).click()
      const history = row.getByRole('list', { name: `History of ${name}` })
      await expect(history).toContainText(`Couldn’t check. ${now?.problem ?? 'missing'}`)
      await expect(history).toContainText(`Checked. The newest version is ${was?.newest_version ?? 'missing'}.`)
      onPage[name] = { row: await text(row), history: await text(history) }
    }
    await expect(page.getByRole('heading', { name: /^Up to date/ })).toHaveCount(0)
    await expect(page.getByText('The last check stopped', { exact: false })).toHaveText('The last check stopped: an agent could not finish its work.')
    await expect(page.getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', `/runs/${runId}`)
    await shotTo(page, 6, 'p6-cant-check.png', true)
    save(6, 'p6-cant-check.json', {
      first,
      runId,
      before: before.software.map((r) => ({ name: r.name, status: r.status, newest: r.newest_version, checked_at: r.checked_at })),
      after: view.software.map((r) => ({ name: r.name, status: r.status, problem: r.problem, newest: r.newest_version, newest_read_at: r.newest_read_at, checked_at: r.checked_at })),
      lastCheck: view.last_check,
      onPage,
    })
    expect(before.software.map((r) => r.status), 'both rows were Up to date first').toEqual(['up_to_date', 'up_to_date'])
    for (const row of view.software) {
      const was = before.software.find((r) => r.id === row.id)
      expect(row.status, `${row.name} status`).toBe('cant_check')
      expect(row.problem, `${row.name} keeps its own reason`).toContain('GitHub')
      expect(row.problem, `${row.name} has its own reason, not the shared sentence`).not.toMatch(/^None of the/)
      expect(row.newest_version, `${row.name} keeps the newest version it last read`).toBe(was?.newest_version)
      expect(row.newest_read_at, `${row.name} says when it was read`).toBe(was?.checked_at)
    }
    expect(view.last_check).toMatchObject({ run_id: runId, state: 'failed' })
    assertClean(watch)
    await context.close()
  })
})

test('@lane7 after an approved ticket is marked Done, history shows the new version and that it came from the ticket', async ({ browser }) => {
  await withBackend(async (backend) => {
    const { runId, approvalId } = await backend.waitingRun('alice', [LANGGRAPH])
    const approval = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
    await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest: approval.digest }, {}, [201])
    await backend.waitForState(runId, ['succeeded'])
    const ticket = (await backend.tickets()).find((item) => item.run_id === runId)
    expect(ticket, 'the approved run made a ticket').toBeDefined()
    await backend.post('alice', `/api/v1/mock-jira/tickets/${ticket?.key}/done`, undefined, {}, [200])
    const api = await rowNamed(backend, 'LangGraph')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    const row = rowOf(page, 'LangGraph')
    await expect(row).toContainText(`From ${ticket?.key}, marked Done`)
    await row.getByRole('button', { name: /^History/ }).click()
    const history = row.getByRole('list', { name: 'History of LangGraph' })
    await expect(history).toContainText(`Our version moved to ${api.our_version}. It came from ${ticket?.key}, marked Done.`)
    await shotTo(page, 7, 'p6-history.png', true)
    save(7, 'p6-history.json', { runId, ticket: ticket?.key, row: api, historyOnPage: await text(history) })
    expect(api.our_version_source?.kind).toBe('ticket_done')
    expect(api.our_version).not.toBe(LANGGRAPH.our_version)
    assertClean(watch)
    await context.close()
  })
})

test('@lane8 at 390 px each row stacks with its status and actions in view and nothing scrolls sideways', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [LANGGRAPH, REDIS, ...manyRows(2)])
    const context = await devContext(browser, 'alice', { phone: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await expect(rowOf(page, 'LangGraph')).toBeVisible()
    const measured = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      rows: [...document.querySelectorAll('li[data-status]')].map((li) => {
        const box = li.getBoundingClientRect()
        const inside = (el: Element | null) => (el ? el.getBoundingClientRect().right <= window.innerWidth + 0.5 && el.getBoundingClientRect().left >= -0.5 : false)
        return { name: li.querySelector('b')?.textContent ?? '', width: box.width, pillIn: inside(li.querySelector('span[data-tone]')), buttonsIn: [...li.querySelectorAll('button')].every(inside) }
      }),
    }))
    await shotTo(page, 8, 'p6-phone.png', true)
    save(8, 'p6-phone.json', measured)
    expect(measured.scrollWidth, 'no sideways scroll').toBeLessThanOrEqual(measured.innerWidth)
    for (const row of measured.rows) {
      expect(row.pillIn, `${row.name}: status in view`).toBe(true)
      expect(row.buttonsIn, `${row.name}: actions in view`).toBe(true)
    }
    assertClean(watch)
    await context.close()
  })
})

test('@lane9 axe finds no WCAG 2.2 AA problems on the page or the add form', async ({ browser }) => {
  await withBackend(async (backend) => {
    const runId = await backend.startCheck('alice', [LANGGRAPH, REDIS])
    await backend.waitForState(runId, ['awaiting_approval'])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^History/ }).click()
    await expectAccessible(page, laneDir(9), 'p6-axe')
    await page.getByLabel('Name', { exact: true }).fill('Bad one')
    await page.getByLabel('GitHub repository').fill('nope')
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.locator('#sw-repo-error')).toBeVisible()
    await expectAccessible(page, laneDir(9), 'p6-axe-add-form')
    await page.getByRole('button', { name: 'Change schedule' }).or(page.getByRole('button', { name: 'Set a schedule' })).click()
    await expectAccessible(page, laneDir(9), 'p6-axe-schedule-form')
    assertClean(watch)
    await context.close()
  })
})

test('@lane10 search filters 14 rows as you type and a screen reader hears the count', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [LANGGRAPH, ...manyRows(13)])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await expect(page.locator('li[data-status]')).toHaveCount(14)
    const find = page.getByRole('searchbox', { name: 'Find software' })
    const live = page.getByRole('status').filter({ has: page.locator('xpath=self::p[contains(@class,"visually-hidden")]') })
    const heard: string[] = []
    for (const [typed, rows, said] of [['T', 13, '13 matches'], ['Tool 0', 9, '9 matches'], ['Tool 07', 1, '1 match']] as const) {
      await find.fill('')
      await find.pressSequentially(typed)
      await expect(page.locator('li[data-status]')).toHaveCount(rows)
      await expect(live).toHaveText(said)
      heard.push(await text(live))
    }
    await find.fill('lang')
    await expect(page.locator('li[data-status]')).toHaveCount(1)
    await expect(live).toHaveText('1 match')
    await shotTo(page, 10, 'p6-search.png', true)
    await find.fill('zzz')
    await expect(page.getByText('Nothing matches')).toBeVisible()
    await expect(live).toHaveText('No matches')
    heard.push(await text(live))
    save(10, 'p6-search.json', { heard, liveRegionRole: await live.getAttribute('role'), liveRegionAria: await live.getAttribute('aria-live') })
    assertClean(watch)
    await context.close()
  })
})

test('@lane11 alice pauses the watchlist through the API, and the page says Paused with no next check time; resuming brings the time back', async ({ browser }) => {
  await withBackend(async (backend) => {
    const useCaseId = await backend.freshWatchlist('alice', [LANGGRAPH])
    await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const schedule = page.locator('section[aria-labelledby="schedule-heading"]')
    try {
      await openSoftware(page)
      await expect(schedule).toContainText('Next check ')
      await shotTo(page, 11, 'p6-on.png', true)
      await backend.post('alice', `/api/v1/use-cases/${useCaseId}/pause`)
      const paused = await viewOf(backend)
      await openSoftware(page)
      await expect(schedule).toContainText('Paused. No check runs until an Operator resumes it.')
      const pausedText = await text(schedule)
      await shotTo(page, 11, 'p6-paused.png', true)
      save(11, 'p6-paused.json', { state: paused.state, next_at: paused.schedule?.next_at ?? null, onPage: pausedText })
      expect(paused.state).toBe('paused')
      expect(paused.schedule?.next_at).toBeNull()
      expect(pausedText).not.toContain('Next check')
      await expect(page.getByRole('button', { name: 'Check now' })).toHaveCount(0)
      const byHand = await backend.send('POST', 'alice', `/api/v1/use-cases/${useCaseId}/runs`, undefined, { 'Idempotency-Key': randomUUID() })
      expect(byHand.status, 'a paused watchlist starts no check by hand').toBe(409)

      await backend.delete('alice', '/api/v1/watchlist/schedule')
      await openSoftware(page)
      await expect(schedule).toContainText('No schedule. Paused. No check runs until an Operator resumes it.')
      await expect(page.getByText(/Press Check now/)).toHaveCount(0)
      await addInForm(page, REDIS)
      await expect(rowOf(page, 'Redis')).toBeVisible()
      await expect(notice(page)).toHaveText('Added Redis. It can be checked once an Operator resumes the watchlist.')
      await shotTo(page, 11, 'p6-paused-no-schedule.png', true)
      save(11, 'p6-paused-no-schedule.json', { byHand, scheduleText: await text(schedule), addedNotice: await text(notice(page)) })

      await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
      await backend.post('alice', `/api/v1/use-cases/${useCaseId}/resume`)
      await openSoftware(page)
      await expect(schedule).toContainText('Next check ')
      await expect(schedule).not.toContainText('Paused')
      await expect(page.getByRole('button', { name: 'Check now' })).toBeVisible()
      assertClean(watch)
    } finally {
      await backend.post('alice', `/api/v1/use-cases/${useCaseId}/resume`)
      await context.close()
    }
  })
})

test('@perf largest contentful paint of the page with 14 watched software', async ({ browser }) => {
  await withBackend((backend) => backend.freshWatchlist('alice', [LANGGRAPH, ...manyRows(13)]))
  const context = await devContext(browser, 'alice')
  await context.addInitScript(() => {
    const w = window as unknown as { __rowsAt?: number }
    new MutationObserver(() => {
      if (w.__rowsAt === undefined && document.querySelectorAll('li[data-status]').length >= 14) {
        requestAnimationFrame(() => {
          w.__rowsAt = performance.now()
        })
      }
    }).observe(document, { childList: true, subtree: true })
  })
  const page = await context.newPage()
  await page.goto('/software', { waitUntil: 'load' })
  await expect(page.locator('li[data-status]')).toHaveCount(14, { timeout: 30_000 })
  await page.waitForFunction(() => (window as unknown as { __rowsAt?: number }).__rowsAt !== undefined)
  const rowsAt = await page.evaluate(() => (window as unknown as { __rowsAt: number }).__rowsAt)
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
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, rows: 14, lcp: last?.startTime ?? -1, element: last?.element ?? '', rowsAt, entries: measured.entries })
  await context.close()
})

test('@review-video alice adds software and runs a check, in 30 to 60 seconds', async ({ browser }) => {
  test.setTimeout(240_000)
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [])
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
      locale: 'en-SG',
      timezoneId: 'Asia/Singapore',
    })
    await context.addInitScript(() => window.localStorage.setItem('portal.dev-user', 'alice'))
    const started = Date.now()
    const page = await context.newPage()
    const video = page.video()
    await openSoftware(page)
    await page.waitForTimeout(2_500)
    const typeInto = async (label: string | RegExp, value: string) => {
      const field = typeof label === 'string' ? page.getByLabel(label, { exact: true }) : page.getByLabel(label)
      await field.click()
      await field.pressSequentially(value, { delay: 90 })
      await page.waitForTimeout(600)
    }
    await typeInto('Name', 'FastAPI')
    await typeInto('GitHub repository', 'https://github.com/fastapi/fastapi')
    await typeInto(/^Our version/, '0.115.0')
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(rowOf(page, 'FastAPI')).toContainText('Not checked yet')
    await page.waitForTimeout(3_000)
    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page).toHaveURL(/\/runs\//)
    await expect(h1(page)).toHaveText(/waiting for a yes$/, { timeout: 90_000 })
    await page.waitForTimeout(5_000)
    await openSoftware(page)
    const row = rowOf(page, 'FastAPI')
    await expect(row).toContainText('Ticket waiting for a yes', { timeout: 30_000 })
    await page.waitForTimeout(2_500)
    await row.getByRole('button', { name: /^History/ }).click()
    await page.waitForTimeout(3_000)
    const pad = (VIDEO_SECONDS.min + 2) * 1000 - (Date.now() - started)
    if (pad > 0) await page.waitForTimeout(pad)
    const seconds = (Date.now() - started) / 1000
    await context.close()
    await video?.saveAs(path.join(EVID, 'p6-review.webm'))
    save('video', 'p6-review.json', { seconds })
    expect(seconds, 'the review video runs 30 to 60 seconds').toBeGreaterThanOrEqual(VIDEO_SECONDS.min)
    expect(seconds).toBeLessThanOrEqual(VIDEO_SECONDS.max)
  })
})
