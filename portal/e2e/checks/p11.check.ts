import AxeBuilder from '@axe-core/playwright'
import { expect, request, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { Backend, setMockGithubMode, type WaitingRun } from '../live/support/stack'
import { devContext, openContext } from '../live/support/ui'
import { assertClean, watchPage } from '../support/test'

// The checker's P11 lanes. scripts/checks/p11.sh runs them in the browser runner image, inside a stack's Portal
// container, so the page is at http://localhost:8080 and compose names such as mock-github resolve.
const EVID = process.env['EVID'] ?? '/tmp/swarm-p11'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const AUTHORITY = process.env['MOCK_OIDC_URL'] ?? 'http://mock-oidc:8080/default'
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const NOT_BUILT = 'This page is not built yet.'
const PHONE = { width: 390, height: 844 }

interface HomeAnswer {
  approvals: { run_id: string; approval_id: string; started_at: string }[]
  approvals_total: number
  confirmations: { confirmation_id: string; kind: string; about_name: string | null }[]
  stopped: { run_id: string; advice: { explanation: string } }[]
  waiting_on_others: { run_id: string; because: string }[]
  drafts: { draft_id: string; name: string | null; step: number }[]
  workflows: number
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

function savedBySetup<T>(lane: number, by: string): T {
  const file = path.join(laneDir(lane), 'seed.json')
  if (!existsSync(file)) throw new Error(`no ${file}; run ${by} first`)
  return JSON.parse(readFileSync(file, 'utf8')) as T
}

/** Waits for one-off motion to end, so a shot shows the page at rest. */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'), undefined, { timeout: 5_000 }).catch(() => undefined)
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = false): Promise<void> {
  await settle(page)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })
const needsYou = (page: Page) => page.getByRole('list', { name: 'Needs you' })
const approvalItem = (page: Page, approvalId: string) => page.locator(`li[data-home-item="approval:${approvalId}"]`)
const waitingOnOthers = (page: Page) => page.getByRole('region', { name: 'Waiting on others' })
const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })

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

async function call(api: APIRequestContext, user: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', url: string, data?: unknown, auth?: string): Promise<{ status: number; body: unknown }> {
  const headers: Record<string, string> = auth ? { Authorization: `Bearer ${auth}` } : { 'X-Dev-User': user }
  const response = await api.fetch(url, { method, headers, ...(data === undefined ? {} : { data }) })
  const text = await response.text()
  return { status: response.status(), body: text ? (JSON.parse(text) as unknown) : null }
}

async function homeOf(api: APIRequestContext, user: string, auth?: string): Promise<HomeAnswer> {
  const answer = await call(api, user, 'GET', '/api/v1/home', undefined, auth)
  expect(answer.status, `GET /api/v1/home as ${user}`).toBe(200)
  return answer.body as HomeAnswer
}

async function openHome(browser: Browser, user: string, options: { phone?: boolean; reducedMotion?: boolean } = {}): Promise<Page> {
  const context = await devContext(browser, user, options)
  const page = await context.newPage()
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 2, name: /^Needs you/ })).toBeVisible()
  return page
}

async function markNotReloaded(page: Page): Promise<void> {
  await page.evaluate(() => {
    ;(window as unknown as { __p11: string }).__p11 = 'same page'
  })
}

async function stillTheSamePage(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __p11?: string }).__p11 === 'same page')
}

async function axeOf(page: Page): Promise<string[]> {
  await settle(page)
  const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
  return result.violations.map((v) => `${v.id} (${v.impact ?? 'unknown'}): ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
}

test('@lane1-trunk trunk has no Home: the P1 empty page', async ({ browser }) => {
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(h1(page)).toHaveText(/^Good (morning|afternoon|evening), Bob$/)
  await shotTo(page, 1, 'p11-home-trunk.png')
  save(1, 'p11-home-trunk.json', { target: 'trunk', main: await page.getByRole('main').innerText() })
  await expect(page.getByRole('main')).toContainText(NOT_BUILT)
  await context.close()
})

test('@lane1 alice starts a watchlist check, and bob’s first item on Home is that run, with one button that opens it', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const page = await openHome(browser, 'bob')
    const watch = watchPage(page)
    await expect(page.getByRole('main')).not.toContainText(NOT_BUILT)
    const first = needsYou(page).locator('li[data-home-item]').first()
    await expect(first).toHaveAttribute('data-home-item', `approval:${approvalId}`)
    const links = await first.getByRole('link').evaluateAll((all) => all.map((a) => [a.textContent?.trim(), a.getAttribute('href')]))
    const buttons = await first.getByRole('button').allInnerTexts()
    await shotTo(page, 1, 'p11-bob-home.png')
    save(1, 'p11-bob-home.json', { target: TARGET, runId, approvalId, first: await first.innerText(), links, buttons, api: await homeOf(api, 'bob') })
    expect(links).toEqual([['Review and decide', `/runs/${runId}`]])
    expect(buttons, 'the item decides nothing itself').toEqual([])
    await first.getByRole('link', { name: 'Review and decide' }).click()
    await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
    await expect(page.locator('#decision'), 'the run opens at the decision').toBeFocused()
    await shotTo(page, 1, 'p11-bob-run-at-decision.png')
    assertClean(watch)
    await page.context().close()
  })
})

test('@lane2 alice, who started the run, sees it under Waiting on others with no Approve button', async ({ browser }) => {
  await withBackend(async (backend, api) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const page = await openHome(browser, 'alice')
    const row = waitingOnOthers(page).locator(`a[href="/runs/${runId}"]`)
    await expect(row).toBeVisible()
    await shotTo(page, 2, 'p11-alice-home.png', true)
    const answer = await homeOf(api, 'alice')
    save(2, 'p11-alice-home.json', { runId, approvalId, row: await row.innerText(), approveButtons: await page.getByRole('button', { name: /^Approve/ }).count(), api: answer })
    await expect(row).toContainText('You started it')
    await expect(approvalItem(page, approvalId)).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Approve/ })).toHaveCount(0)
    expect(answer.approvals.map((a) => a.run_id)).not.toContain(runId)
    expect(answer.waiting_on_others.find((w) => w.run_id === runId)?.because).toBe('started')
    await page.context().close()
  })
})

test('@lane3 bob approves from Home and the item leaves his Home without a reload, from the run page and from Teams', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (backend) => {
    const viaRunPage: WaitingRun = await backend.waitingRun('alice')
    const page = await openHome(browser, 'bob')
    await expect(approvalItem(page, viaRunPage.approvalId)).toBeVisible()
    await markNotReloaded(page)
    await approvalItem(page, viaRunPage.approvalId).getByRole('link', { name: 'Review and decide' }).click()
    await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
    await backend.waitToLeave(viaRunPage.runId, 'awaiting_approval')
    await mainMenu(page).getByRole('link', { name: 'Home' }).click()
    await expect(page.getByRole('heading', { level: 2, name: /^Needs you/ })).toBeVisible()
    await expect(approvalItem(page, viaRunPage.approvalId)).toHaveCount(0)
    const sameAfterRunPage = await stillTheSamePage(page)
    await shotTo(page, 3, 'p11-after-approve.png')

    const viaTeams = await backend.waitingRun('alice')
    await expect(approvalItem(page, viaTeams.approvalId)).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
    const message = page.getByRole('dialog', { name: 'Teams, practice copy' }).locator(`li[data-approval-id="${viaTeams.approvalId}"]`)
    await message.scrollIntoViewIfNeeded()
    await message.getByRole('button', { name: 'Approve' }).click()
    await expect(message).toContainText('Approved by Bob')
    const decidedAt = Date.now()
    await page.keyboard.press('Escape')
    await expect(approvalItem(page, viaTeams.approvalId)).toHaveCount(0, { timeout: 5_000 })
    const leftAfterMs = Date.now() - decidedAt
    const sameAfterTeams = await stillTheSamePage(page)
    await shotTo(page, 3, 'p11-after-teams-yes.png')
    save(3, 'p11-after-approve.json', { viaRunPage, viaTeams, sameAfterRunPage, sameAfterTeams, leftAfterMs })
    expect(sameAfterRunPage, 'no reload between the run page and Home').toBe(true)
    expect(sameAfterTeams, 'no reload after the yes in Teams').toBe(true)
    await page.context().close()
  })
})

test('@lane4 a run alice started stops; her Home shows it with the AI troubleshooter’s reason and Retry', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (backend, api) => {
    const watchlist = await backend.freshWatchlist('alice')
    await setMockGithubMode('unavailable')
    let runId = ''
    try {
      runId = await backend.checkNow('alice', watchlist)
      await backend.waitForState(runId, ['failed'], 240_000)
    } finally {
      await setMockGithubMode('ok')
    }
    const page = await openHome(browser, 'alice')
    const item = page.locator(`li[data-home-item="stopped:${runId}"]`)
    await expect(item).toBeVisible()
    await shotTo(page, 4, 'p11-stopped.png')
    const answer = await homeOf(api, 'alice')
    save(4, 'p11-stopped.json', { runId, item: await item.innerText(), buttons: await item.getByRole('button').allInnerTexts(), api: answer })
    await expect(item).toContainText('Software watchlist stopped')
    await expect(item).toContainText('AI troubleshooter')
    await expect(item).toContainText(answer.stopped.find((s) => s.run_id === runId)?.advice.explanation ?? 'no reason in the API')
    const retry = item.getByRole('button', { name: 'Retry the run' })
    await expect(retry).toBeVisible()
    await retry.click()
    await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
    await backend.waitToLeave(runId, 'failed')
    await shotTo(page, 4, 'p11-retried.png')
    await page.context().close()
  })
})

test('@lane5 alice asks for a new Approver; bob sees the confirmation on Home and alice does not', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    const asked = await call(api, 'alice', 'POST', '/api/v1/people/carol/approver')
    expect([202, 409], `alice asks for carol as an Approver: ${JSON.stringify(asked.body)}`).toContain(asked.status)
    const page = await openHome(browser, 'bob')
    const item = needsYou(page).locator('li[data-home-item^="confirmation:"]', { hasText: 'Confirm Carol as an Approver' })
    await expect(item).toBeVisible()
    await shotTo(page, 5, 'p11-confirmation.png')
    const homes = { bob: await homeOf(api, 'bob'), alice: await homeOf(api, 'alice'), carol: await homeOf(api, 'carol') }
    save(5, 'p11-confirmation.json', { asked, link: await item.getByRole('link').getAttribute('href'), homes })
    await expect(item.getByRole('link', { name: 'Review in Settings' })).toHaveAttribute('href', '/settings?tab=people')
    expect(homes.bob.confirmations.map((c) => c.about_name)).toContain('Carol')
    expect(homes.alice.confirmations, 'the asker does not confirm her own request').toEqual([])
    expect(homes.carol.confirmations, 'nobody confirms a role for themselves').toEqual([])
    const alice = await openHome(browser, 'alice')
    await expect(alice.locator('li[data-home-item^="confirmation:"]')).toHaveCount(0)
    await alice.context().close()
    await page.context().close()
  })
})

test('@lane6 alice saves a draft, and Home shows it under Your drafts', async ({ browser }) => {
  await withBackend(async (_backend, api) => {
    const draftId = `p11-lane6-${randomUUID().slice(0, 8)}`
    const name = `p11 lane6 ${draftId.slice(-8)}`
    const saved = await call(api, 'alice', 'PUT', `/api/v1/drafts/${draftId}`, { step: 2, content: { name, intent: 'Every Wednesday, nudge owners of stale tickets in MOCK.' } })
    expect(saved.status, JSON.stringify(saved.body)).toBe(200)
    try {
      const page = await openHome(browser, 'alice')
      const drafts = page.getByRole('region', { name: 'Your drafts' })
      const row = drafts.locator(`li[data-draft="${draftId}"]`)
      await expect(row).toBeVisible()
      await row.scrollIntoViewIfNeeded()
      await shotTo(page, 6, 'p11-draft.png')
      save(6, 'p11-draft.json', { saved, row: await row.innerText() })
      await expect(row).toContainText(name)
      await expect(row).toContainText('Step 2 of 4')
      await page.context().close()
    } finally {
      await call(api, 'alice', 'DELETE', `/api/v1/drafts/${draftId}`)
    }
  })
})

interface SignedIn {
  readonly page: Page
  readonly token: () => string
}

async function signIn(browser: Browser, user: string): Promise<SignedIn> {
  const context = await openContext(browser)
  const page = await context.newPage()
  let token = ''
  page.on('response', (response) => {
    if (response.request().method() !== 'POST' || response.url() !== `${AUTHORITY}/token` || !response.ok()) return
    void response.json().then((body: { access_token?: string }) => {
      if (body.access_token) token = body.access_token
    })
  })
  await page.goto('/')
  const username = page.locator('input[name="username"]')
  await expect(username, 'the Portal sends a signed-out person to the identity provider').toBeVisible({ timeout: 60_000 })
  await username.fill(user)
  await page.locator('input[type="submit"]').click()
  await expect(h1(page)).toBeVisible()
  await expect.poll(() => token, { message: `the Portal holds a token for ${user}` }).not.toBe('')
  return { page, token: () => token }
}

test('@lane7-oidc erin, a new Operator with nothing to do, signs in and Home says Nothing needs you yet and How it works', async ({ browser }) => {
  test.setTimeout(400_000)
  await withBackend(async (_backend, api) => {
    const alice = await signIn(browser, 'alice')
    const added = await call(api, 'alice', 'POST', '/api/v1/people', { email: 'erin@example.test', display: 'Erin', operator: true }, alice.token())
    expect([201, 409], `alice adds erin as an Operator: ${JSON.stringify(added.body)}`).toContain(added.status)
    await alice.page.context().close()

    const erin = await signIn(browser, 'erin')
    const page = erin.page
    await expect(page.getByRole('heading', { level: 2, name: /^Needs you/ })).toBeVisible()
    await shotTo(page, 7, 'p11-day-one.png', true)
    const answer = await homeOf(api, 'erin', erin.token())
    save(7, 'p11-day-one.json', { added, main: await page.getByRole('main').innerText(), api: answer })
    await expect(page.getByRole('main')).toContainText('Nothing needs you yet.')
    await expect(page.getByRole('region', { name: 'How it works' }).locator('ol > li')).toHaveCount(4)

    const axe: Record<string, string[]> = { 'erin-1440': await axeOf(page) }
    await page.setViewportSize(PHONE)
    axe['erin-390'] = await axeOf(page)
    await shotTo(page, 9, 'p11-erin-390.png', true)
    save(9, 'p11-axe-erin.json', axe)
    expect(axe, 'WCAG 2.2 AA on erin’s day-one Home').toEqual({ 'erin-1440': [], 'erin-390': [] })
    await page.context().close()
  })
})

test('@lane8 carol, who is not an Approver, gets no approval items from GET /api/v1/home', async () => {
  await withBackend(async (backend, api) => {
    const { runId } = await backend.waitingRun('alice')
    const carol = await call(api, 'carol', 'GET', '/api/v1/home')
    const bob = await homeOf(api, 'bob')
    save(8, 'p11-carol.json', carol.body)
    save(8, 'p11-bob-same-moment.json', bob)
    expect(carol.status).toBe(200)
    expect(bob.approvals.map((a) => a.run_id), 'a run waits that an Approver may decide').toContain(runId)
    const answer = carol.body as HomeAnswer
    expect(answer.approvals).toEqual([])
    expect(answer.approvals_total).toBe(0)
  })
})

test('@lane9 axe finds no WCAG 2.2 AA problem on bob’s Home at 1440 and 390 px', async ({ browser }) => {
  await withBackend(async (backend) => {
    await backend.waitingRun('alice')
    const found: Record<string, string[]> = {}
    for (const phone of [false, true]) {
      const page = await openHome(browser, 'bob', { phone })
      await expect(needsYou(page)).toBeVisible()
      const name = `bob-${phone ? 390 : 1440}`
      found[name] = await axeOf(page)
      await shotTo(page, 9, `p11-${name}.png`, true)
      const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
      found[`${name}-sideways-scroll`] = (widths[0] ?? 0) > (widths[1] ?? 0) ? [`scrollWidth ${widths[0]} > clientWidth ${widths[1]}`] : []
      await page.context().close()
    }
    save(9, 'p11-axe.json', found)
    for (const [name, problems] of Object.entries(found)) expect(problems, name).toEqual([])
  })
})

test('@lane10-setup one waiting run for the seed to copy', async () => {
  await withBackend(async (backend) => {
    save(10, 'seed.json', await backend.waitingRun('alice'))
  })
})

test('@lane10 with 50 runs waiting, bob’s Home shows the newest first and says how many more wait', async ({ browser }) => {
  const seed = savedBySetup<WaitingRun>(10, 'p11.sh lane10, which runs @lane10-setup and copies the run')
  await withBackend(async (_backend, api) => {
    const answer = await homeOf(api, 'bob')
    const page = await openHome(browser, 'bob')
    const keys = await needsYou(page).locator('li[data-home-item]').evaluateAll((all) => all.map((li) => li.getAttribute('data-home-item')))
    const more = await page.getByText(/more runs? (is|are) waiting for your yes/).innerText()
    await shotTo(page, 10, 'p11-many.png', true)
    save(10, 'p11-many.json', { seed, total: answer.approvals_total, keys, more, approvals: answer.approvals })
    expect(answer.approvals_total).toBeGreaterThanOrEqual(50)
    expect(keys[0]).toBe(`approval:${seed.approvalId}`)
    const times = answer.approvals.map((a) => a.started_at)
    expect(times, 'newest first').toEqual([...times].sort().reverse())
    expect(keys).toEqual(answer.approvals.slice(0, 10).map((a) => `approval:${a.approval_id}`))
    expect(more).toContain(`${answer.approvals_total - 10} more runs are waiting for your yes`)
    await page.context().close()
  })
})

test('@perf largest contentful paint of Home for bob, and when its first item is drawn', async ({ browser }) => {
  const context = await devContext(browser, 'bob')
  await context.addInitScript(() => {
    const w = window as unknown as { __itemAt: number | null }
    w.__itemAt = null
    new MutationObserver(() => {
      if (w.__itemAt === null && document.querySelector('[data-home-item], [class*="quiet"]')) w.__itemAt = performance.now()
    }).observe(document, { childList: true, subtree: true })
  })
  const page = await context.newPage()
  await page.goto('/', { waitUntil: 'load' })
  await expect(page.getByRole('heading', { level: 2, name: /^Needs you/ })).toBeVisible()
  await page.waitForTimeout(1_500)
  const entries = await page.evaluate(
    () =>
      new Promise<{ startTime: number; element: string }[]>((resolve) => {
        const seen: { startTime: number; element: string }[] = []
        const observer = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as (PerformanceEntry & { element: Element | null })[]) {
            seen.push({ startTime: e.startTime, element: e.element ? `${e.element.tagName.toLowerCase()} "${(e.element.textContent ?? '').trim().slice(0, 40)}"` : 'gone' })
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => {
          observer.disconnect()
          resolve(seen)
        }, 500)
      }),
  )
  const itemAt = await page.evaluate(() => (window as unknown as { __itemAt: number | null }).__itemAt)
  const last = entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, lcp: last?.startTime ?? -1, element: last?.element ?? '', itemAt: itemAt ?? -1, entries })
  await context.close()
})

test('@review-video-setup a run waiting for bob, then a run alice started that stops', async () => {
  test.setTimeout(400_000)
  await withBackend(async (backend) => {
    const waiting = await backend.waitingRun('alice')
    const watchlist = (await backend.get<{ watchlist: { use_case_id: string } }>('alice', '/api/v1/watchlist')).watchlist.use_case_id
    await setMockGithubMode('unavailable')
    let stopped = ''
    try {
      stopped = await backend.checkNow('alice', watchlist)
      await backend.waitForState(stopped, ['failed'], 240_000)
    } finally {
      await setMockGithubMode('ok')
    }
    save('review-video', 'seed.json', { waiting, stopped })
  })
})

test('@review-video bob decides from Home, then alice sees her stopped run with the reason', async ({ browser }) => {
  test.setTimeout(400_000)
  const file = path.join(laneDir('review-video'), 'seed.json')
  if (!existsSync(file)) throw new Error(`no ${file}; run @review-video-setup first`)
  const { waiting } = JSON.parse(readFileSync(file, 'utf8')) as { waiting: WaitingRun; stopped: string }
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
  await context.addInitScript(() => {
    if (!window.localStorage.getItem('portal.dev-user')) window.localStorage.setItem('portal.dev-user', 'bob')
  })
  const page = await context.newPage()
  const video = page.video()
  const started = Date.now()
  await page.goto('/')
  await expect(approvalItem(page, waiting.approvalId)).toBeVisible()
  await page.waitForTimeout(5_000)
  const review = approvalItem(page, waiting.approvalId).getByRole('link', { name: 'Review and decide' })
  await review.hover()
  await page.waitForTimeout(1_200)
  await review.click()
  await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
  await page.waitForTimeout(4_000)
  await page.getByRole('button', { name: 'Approve 1 ticket' }).hover()
  await page.waitForTimeout(1_000)
  await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
  await page.waitForTimeout(4_000)
  await mainMenu(page).getByRole('link', { name: 'Home' }).click()
  await expect(approvalItem(page, waiting.approvalId)).toHaveCount(0)
  await page.waitForTimeout(4_000)
  await page.getByRole('button', { name: 'Test controls' }).click()
  await page.getByRole('region', { name: 'Test controls' }).getByRole('button', { name: 'Alice' }).click()
  await page.getByRole('button', { name: 'Test controls' }).click()
  await expect(h1(page)).toContainText('Alice')
  await page.waitForTimeout(2_000)
  const stopped = page.locator('li[data-home-item^="stopped:"]').first()
  await expect(stopped).toBeVisible()
  await stopped.hover()
  await page.waitForTimeout(5_000)
  await stopped.getByRole('button', { name: 'Retry the run' }).hover()
  await page.waitForTimeout(Math.max(3_000, 34_000 - (Date.now() - started)))
  await context.close()
  await video?.saveAs(path.join(EVID, 'p11-review.webm'))
})
