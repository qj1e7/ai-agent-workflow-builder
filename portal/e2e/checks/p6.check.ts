/**
 * The checker's checks for P6's live lanes and perf block (docs/design/rebuild-plan.md): the Software watchlist page.
 * Run through scripts/checks/p6.sh, which picks the stack and the lane with --grep @laneN.
 * Evidence goes to $EVID/lane-<n>/ with the file names the plan gives.
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { Backend, LANGGRAPH, REDIS, setMockGithubMode, type Software } from '../live/support/stack'
import { devContext } from '../live/support/ui'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p6'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const UNDO_WINDOW_MS = 8_000

interface Row {
  id: string
  name: string
  status: string
  problem: string | null
  our_version: string | null
  newest_version: string | null
  our_version_source: { kind: string; ticket: string | null } | null
  open_ticket: string | null
  source: { ref: string }
}

interface View {
  use_case_id: string
  software: Row[]
  last_check: { run_id: string; state: string; started_at: string } | null
  schedule: { day: string; at: string; owner: string; owner_name: string; next_at: string } | null
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
}

async function addInForm(page: Page, software: Software): Promise<void> {
  await page.getByLabel('Name', { exact: true }).fill(software.name)
  await page.getByLabel('GitHub repository').fill(software.repo)
  await page.getByLabel(/^Our version/).fill(software.our_version)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
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

test('@lane1 alice adds software, presses Check now, lands on the run, and the row shows the newest version and a ticket waiting for a yes', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const keys: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/use-cases\/[^/]+\/runs$/.test(request.url())) keys.push(request.headers()['idempotency-key'] ?? '')
    })
    await openSoftware(page)
    await expect(page.getByText('No software yet')).toBeVisible()
    await addInForm(page, LANGGRAPH)
    await expect(rowOf(page, 'LangGraph')).toBeVisible()
    await expect(rowOf(page, 'LangGraph')).toContainText('Not checked yet')
    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = page.url().split('/').at(-1) ?? ''
    await backend.waitForState(runId, ['awaiting_approval'])
    await openSoftware(page)
    const row = rowOf(page, 'LangGraph')
    await expect(row).toContainText('Ticket waiting for a yes', { timeout: 30_000 })
    const api = await rowNamed(backend, 'LangGraph')
    await expect(row).toContainText(api.newest_version ?? 'missing')
    await shotTo(page, 1, 'p6-check.png', true)
    save(1, 'p6-check.json', { runId, idempotencyKeys: keys, row: api, rowOnPage: await text(row) })
    expect(keys, 'one check started with one key').toHaveLength(1)
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/)
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
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 a removed row comes back with its history after Undo, and a removal left alone goes through', async ({ browser }) => {
  await withBackend(async (backend) => {
    const runId = await backend.startCheck('alice', [LANGGRAPH, REDIS])
    await backend.waitForState(runId, ['awaiting_approval'])
    const before = await rowNamed(backend, 'LangGraph')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const deletes: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'DELETE' && request.url().includes('/watchlist/software/')) deletes.push(request.url())
    })
    await openSoftware(page)
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^Remove/ }).click()
    await expect(rowOf(page, 'LangGraph')).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: 'Removed LangGraph.' })).toBeVisible()
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(rowOf(page, 'LangGraph')).toBeVisible()
    await rowOf(page, 'LangGraph').getByRole('button', { name: /^History/ }).click()
    const history = rowOf(page, 'LangGraph').getByRole('list', { name: 'History of LangGraph' })
    await expect(history).toContainText('Checked. The newest version is')
    await page.waitForTimeout(UNDO_WINDOW_MS + 2_000)
    const kept = await rowNamed(backend, 'LangGraph')
    await shotTo(page, 3, 'p6-undo.png', true)
    await rowOf(page, 'Redis').getByRole('button', { name: /^Remove/ }).click()
    await expect(rowOf(page, 'Redis')).toHaveCount(0)
    await expect.poll(async () => (await viewOf(backend)).software.map((r) => r.name), { timeout: UNDO_WINDOW_MS + 8_000 }).toEqual(['LangGraph'])
    save(3, 'p6-undo.json', { before, kept, deletesAfterUndo: deletes, historyOnPage: await text(history) })
    expect(kept.id, 'the same row, not a copy').toBe(before.id)
    expect(deletes, 'only Redis was deleted, after its wait').toHaveLength(1)
    assertClean(watch)
    await context.close()
  })
})

test('@lane4 carol sets the schedule to every Monday at 9:00 and the page shows the next check in Singapore time with carol as owner', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [LANGGRAPH])
    const context = await devContext(browser, 'carol')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await page.getByRole('button', { name: 'Set a schedule' }).click()
    await page.getByLabel('Day').selectOption('monday')
    await page.getByLabel('Time, Singapore').fill('09:00')
    await page.getByRole('button', { name: 'Save schedule' }).click()
    await expect(page.getByText('Checked every Monday at 9:00, set by Carol.')).toBeVisible()
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

test('@lane5 bob, an Approver only, sees the list and no add, remove, schedule or check controls', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [LANGGRAPH, REDIS])
    const refused = await backend.send('POST', 'bob', '/api/v1/watchlist/software', { name: 'Nope', repo: 'acme/nope' })
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    await expect(rowOf(page, 'LangGraph')).toBeVisible()
    const names = await page.getByRole('button').allInnerTexts()
    const controls = names.filter((name) => /^(Check now|Remove|Change schedule|Set a schedule|Turn off schedule|Add)\b/.test(name.trim()))
    await shotTo(page, 5, 'p6-approver-view.png', true)
    save(5, 'p6-approver-view.json', { buttons: names, controls, bobPostStatus: refused.status })
    expect(controls).toEqual([])
    await expect(page.getByRole('heading', { name: 'Add software' })).toHaveCount(0)
    await expect(page.getByLabel('GitHub repository')).toHaveCount(0)
    expect(refused.status, 'the platform also refuses bob').toBe(403)
    assertClean(watch)
    await context.close()
  })
})

test('@lane6 when the mock GitHub fails during a check, the row says it can’t check and will try at the next check, and the page says the check stopped', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [LANGGRAPH])
    await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
    await setMockGithubMode('unavailable')
    let runId = ''
    try {
      runId = await backend.checkNow('alice', (await viewOf(backend)).use_case_id)
      await backend.waitForState(runId, ['failed'], 120_000)
    } finally {
      await setMockGithubMode('ok')
    }
    const view = await viewOf(backend)
    const api = await rowNamed(backend, 'LangGraph')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await openSoftware(page)
    const row = rowOf(page, 'LangGraph')
    await expect(row).toContainText('Can’t check')
    await expect(row).toContainText('It will try again at the next check.')
    await expect(page.getByText('The last check stopped', { exact: false })).toHaveText('The last check stopped: an agent could not finish its work.')
    await expect(page.getByRole('link', { name: 'Open the run' })).toHaveAttribute('href', `/runs/${runId}`)
    await row.getByRole('button', { name: /^History/ }).click()
    const history = row.getByRole('list', { name: 'History of LangGraph' })
    await expect(history).toContainText(`Couldn’t check. ${api.problem ?? 'missing'}`)
    await shotTo(page, 6, 'p6-cant-check.png', true)
    save(6, 'p6-cant-check.json', { runId, lastCheck: view.last_check, row: api, rowOnPage: await text(row), historyOnPage: await text(history) })
    expect(api.status).toBe('cant_check')
    expect(api.problem, 'the row keeps why it could not be checked').toContain('GitHub')
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

test('@perf largest contentful paint of the page with 14 watched software', async ({ browser }) => {
  await withBackend((backend) => backend.freshWatchlist('alice', [LANGGRAPH, ...manyRows(13)]))
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/software', { waitUntil: 'load' })
  await expect(page.locator('li[data-status]')).toHaveCount(14, { timeout: 30_000 })
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
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, rows: 14, lcp: last?.startTime ?? -1, element: last?.element ?? '', entries: measured.entries })
  await context.close()
})

test('@review-video alice adds software and runs a check', async ({ browser }) => {
  test.setTimeout(180_000)
  await withBackend(async (backend) => {
    await backend.freshWatchlist('alice', [])
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
      locale: 'en-SG',
      timezoneId: 'Asia/Singapore',
    })
    await context.addInitScript(() => window.localStorage.setItem('portal.dev-user', 'alice'))
    const page = await context.newPage()
    const video = page.video()
    await openSoftware(page)
    await page.waitForTimeout(1_500)
    await addInForm(page, { name: 'FastAPI', repo: 'fastapi/fastapi', our_version: '0.115.0' })
    await expect(rowOf(page, 'FastAPI')).toBeVisible()
    await page.waitForTimeout(1_500)
    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page).toHaveURL(/\/runs\//)
    await expect(h1(page)).toHaveText(/waiting for a yes$/, { timeout: 90_000 })
    await page.waitForTimeout(1_500)
    await openSoftware(page)
    await expect(rowOf(page, 'FastAPI')).toContainText('Ticket waiting for a yes', { timeout: 30_000 })
    await page.waitForTimeout(2_000)
    await context.close()
    await video?.saveAs(path.join(EVID, 'p6-review.webm'))
  })
})
