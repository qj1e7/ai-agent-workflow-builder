import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import {
  connectMockModel,
  FOLLOW_UP,
  fixRow,
  heading,
  nextButton,
  NO_SCHEDULE,
  planIt,
  pressNext,
  RELEASE,
  rowOf,
  stepHeading,
  TEAMS,
  throughToReview,
  turnOn,
} from '../live/support/newWorkflow'
import { Backend } from '../live/support/stack'
import { devContext } from '../live/support/ui'
import { tabTo } from '../support/keyboard'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p13'
const TARGET = process.env['TARGET'] ?? 'head'
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const PRESSES = 10

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${String(lane)}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'), undefined, { timeout: 5_000 }).catch(() => undefined)
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = true): Promise<void> {
  await settle(page)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })
const planRegion = (page: Page) => page.getByRole('region', { name: 'What the workflow will do' })

async function withBackend<T>(act: (backend: Backend) => Promise<T>): Promise<T> {
  const backend = await Backend.connect(BASE_URL)
  try {
    return await act(backend)
  } finally {
    await backend.dispose()
  }
}

async function openNew(browser: Browser, user = 'alice', phone = false): Promise<Page> {
  const context = await devContext(browser, user, { phone })
  const page = await context.newPage()
  await page.goto('/new')
  await expect(heading(page)).toBeVisible()
  return page
}

async function axeOf(page: Page): Promise<string[]> {
  await settle(page)
  const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
  return result.violations.map((v) => `${v.id} (${v.impact ?? 'unknown'}): ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
}

async function sideways(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}

test.beforeAll(async () => {
  if (TARGET === 'head') await connectMockModel(BASE_URL)
})

test('@lane1-trunk trunk has no New workflow: no menu item, and /new is Page not found', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  const menu = await mainMenu(page).getByRole('link').allInnerTexts()
  await page.goto('/new')
  await expect(heading(page)).toBeVisible()
  const shown = await heading(page).innerText()
  await shotTo(page, 1, 'p13-trunk.png')
  save(1, 'p13-trunk.json', { target: 'trunk', menu, heading: shown })
  expect(menu).not.toContain('New workflow')
  expect(shown).toBe('Page not found')
  await context.close()
})

test('@lane1 alice sets up the follow-up ticket workflow, and it is on Workflows, on, every weekday at 15:00', async ({ browser }) => {
  await withBackend(async (backend) => {
    const name = `p13 lane1 ${randomUUID().slice(0, 6)}`
    const page = await openNew(browser)
    const watch = watchPage(page)
    await planIt(page, FOLLOW_UP)
    await fixRow(page, 'Looks for', 'Bug tickets in MOCK with no update for 14 days')
    await throughToReview(page, name)
    const id = await turnOn(page)
    await shotTo(page, 1, 'p13-done.png')
    await mainMenu(page).getByRole('link', { name: 'Workflows' }).click()
    const row = page.locator(`li[data-workflow-id="${id}"]`)
    await expect(row).toContainText(name)
    const listed = await row.innerText()
    await shotTo(page, 1, 'p13-workflows.png')
    await row.getByRole('link', { name }).click()
    await expect(page.getByRole('main')).toContainText('Every weekday at 15:00')
    await shotTo(page, 1, 'p13-workflow-page.png')
    const api = await backend.get<{ state: string; schedule: { day: string; at: string } | null; next_run_at: string | null; owner: string }>('alice', `/api/v1/use-cases/${id}`)
    save(1, 'p13-done.json', { target: TARGET, id, name, listed, api })
    expect(listed).toContain('On')
    expect(api).toMatchObject({ state: 'on', schedule: { day: 'weekdays', at: '15:00' }, owner: 'alice' })
    expect(api.next_run_at).not.toBeNull()
    assertClean(watch)
    await page.context().close()
  })
})

test('@lane2 a release task offers the Software watchlist and names the word that made the Planner think so', async ({ browser }) => {
  const page = await openNew(browser)
  await planIt(page, RELEASE)
  const said = await page.getByRole('main').innerText()
  await shotTo(page, 2, 'p13-to-watchlist.png')
  save(2, 'p13-to-watchlist.json', { task: RELEASE, said })
  await expect(page.getByRole('main')).toContainText('You mentioned “release”')
  await expect(page.getByRole('link', { name: 'Open Software watchlist' })).toHaveAttribute('href', '/software')
  await page.context().close()
})

test('@lane3 No, set it up as a new workflow opens step 2 with the task kept', async ({ browser }) => {
  const page = await openNew(browser)
  await planIt(page, RELEASE)
  await page.getByRole('button', { name: 'No, set it up as a new workflow' }).click()
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(heading(page)).toBeFocused()
  const words = await page.locator('blockquote').innerText()
  await shotTo(page, 3, 'p13-carry-on.png')
  save(3, 'p13-carry-on.json', { words, fillIns: await page.getByRole('button', { name: 'Fill in' }).count() })
  expect(words).toContain(RELEASE)
  await expect(page.getByRole('button', { name: 'Fill in' })).toHaveCount(4)
  await page.context().close()
})

test('@lane4 with the schedule missing, Next stays off and pressing it points at the missing row', async ({ browser }) => {
  const page = await openNew(browser)
  await planIt(page, NO_SCHEDULE)
  await expect(rowOf(page, 'When')).toContainText('please fill in')
  await pressNext(page)
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(rowOf(page, 'When').getByRole('button', { name: 'Fill in' })).toBeFocused()
  await shotTo(page, 4, 'p13-missing.png')
  save(4, 'p13-missing.json', {
    when: await rowOf(page, 'When').innerText(),
    next: await nextButton(page).getAttribute('aria-disabled'),
    why: await page.locator('#next-why').innerText(),
  })
  await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'true')
  await expect(page.locator('#next-why')).toHaveText('Next opens when you say when it runs.')
  await page.context().close()
})

test('@lane5 a task that posts in Teams marks that part can’t do yet and explains it', async ({ browser }) => {
  const page = await openNew(browser)
  await planIt(page, TEAMS)
  const where = rowOf(page, 'Where it goes')
  await expect(where).toContainText('can’t do this yet')
  const said = await where.innerText()
  await shotTo(page, 5, 'p13-cant-yet.png')
  save(5, 'p13-cant-yet.json', { task: TEAMS, where: said, plan: await planRegion(page).innerText() })
  expect(said).toMatch(/Teams/)
  await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'true')
  await expect(planRegion(page)).not.toContainText('Changes data')
  await page.context().close()
})

test('@lane6 a draft saved and closed shows on Home, and opening it returns to the same step', async ({ browser }) => {
  const page = await openNew(browser)
  const mark = randomUUID().slice(0, 6)
  await planIt(page, FOLLOW_UP)
  await fixRow(page, 'Does', `Create one follow-up ticket that lists them, ${mark}`)
  await expect(planRegion(page)).toContainText('Changes data, waits for a yes')
  await page.getByRole('button', { name: 'Save draft and close' }).click()
  await expect(page).toHaveURL(/\/$/)
  const drafts = page.getByRole('region', { name: 'Your drafts' })
  const row = drafts.getByRole('link').first()
  await expect(row).toContainText('Step 2 of 4')
  await shotTo(page, 6, 'p13-draft.png')
  const listed = await drafts.innerText()
  await row.click()
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(rowOf(page, 'Does')).toContainText(mark)
  await shotTo(page, 6, 'p13-draft-reopened.png')
  save(6, 'p13-draft.json', { listed, url: page.url(), heading: await heading(page).innerText() })
  await page.context().close()
})

test('@lane7 a test run from the done page waits for bob, his yes takes it to Done, and the practice Jira holds the ticket', async ({ browser }) => {
  test.setTimeout(300_000)
  await withBackend(async (backend) => {
    const page = await openNew(browser)
    await planIt(page, FOLLOW_UP)
    await throughToReview(page, `p13 lane7 ${randomUUID().slice(0, 6)}`)
    await turnOn(page)
    await page.getByRole('button', { name: 'Do a test run now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = /\/runs\/([^/?#]+)$/.exec(page.url())?.[1] ?? ''
    await backend.waitForState(runId, ['awaiting_approval'], 180_000)
    const bob = await devContext(browser, 'bob')
    const bobPage = await bob.newPage()
    await bobPage.goto(`/runs/${runId}`)
    await bobPage.getByRole('button', { name: 'Approve 1 ticket' }).click()
    const done = await backend.waitForState(runId, ['succeeded'], 180_000)
    await page.reload()
    await expect(page.getByRole('main')).toContainText(/created in Jira|Done/)
    await shotTo(page, 7, 'p13-test-run.png')
    const tickets = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
    save(7, 'p13-test-run.json', { runId, state: done, tickets })
    expect(tickets).toHaveLength(1)
    await bob.close()
    await page.context().close()
  })
})

test('@lane8 with the keyboard alone, each step’s heading takes focus and says which step it is', async ({ browser }) => {
  const page = await openNew(browser)
  const seen: { step: string; focused: boolean }[] = []
  const note = async () =>
    seen.push({ step: ((await heading(page).textContent()) ?? '').replace(/\s+/g, ' ').trim(), focused: await heading(page).evaluate((el) => el === document.activeElement) })
  await tabTo(page, page.getByLabel('What should happen?'))
  await page.keyboard.type(FOLLOW_UP)
  await tabTo(page, page.getByRole('button', { name: 'Plan it' }))
  await page.keyboard.press('Enter')
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(planRegion(page)).toContainText('Changes data, waits for a yes')
  await note()
  await tabTo(page, nextButton(page), 60)
  await page.keyboard.press('Enter')
  await expect(heading(page)).toHaveText(stepHeading(3, 'When it runs'))
  await note()
  await tabTo(page, nextButton(page))
  await page.keyboard.press('Enter')
  await expect(heading(page)).toHaveText(stepHeading(4, 'Turn it on'))
  await note()
  await tabTo(page, page.getByRole('button', { name: 'Turn it on' }), 60)
  await shotTo(page, 8, 'p13-keyboard.png')
  save(8, 'p13-keyboard.json', seen)
  expect(seen.map((s) => s.focused)).toEqual([true, true, true])
  expect(seen.map((s) => s.step)).toEqual(['New workflow, step 2 of 4: Check what I understood', 'New workflow, step 3 of 4: When it runs', 'New workflow, step 4 of 4: Turn it on'])
  await page.context().close()
})

test('@lane9 axe finds no WCAG 2.2 AA problem on any step at 1440 and 390 px', async ({ browser }) => {
  test.setTimeout(300_000)
  const found: Record<string, { violations: string[]; sideways: number }> = {}
  for (const phone of [false, true]) {
    const size = phone ? '390' : '1440'
    const page = await openNew(browser, 'alice', phone)
    const look = async (step: number) => {
      found[`step-${String(step)}-${size}`] = { violations: await axeOf(page), sideways: await sideways(page) }
      await shotTo(page, 9, `p13-step-${String(step)}-${size}.png`)
    }
    await look(1)
    await planIt(page, FOLLOW_UP)
    await expect(planRegion(page)).toContainText('Changes data, waits for a yes')
    await look(2)
    await nextButton(page).click()
    await look(3)
    await nextButton(page).click()
    await look(4)
    await page.context().close()
  }
  save(9, 'p13-axe.json', found)
  for (const [where, result] of Object.entries(found)) {
    expect(result.violations, where).toEqual([])
    expect(result.sideways, `${where} scrolls sideways`).toBeLessThanOrEqual(0)
  }
})

test('@lane10 bob has no New workflow in the menu, and its page says only Operators set up workflows', async ({ browser }) => {
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  const menu = await mainMenu(page).getByRole('link').allInnerTexts()
  await page.goto('/new')
  await expect(heading(page)).toHaveText('New workflow')
  await shotTo(page, 10, 'p13-approver.png')
  save(10, 'p13-approver.json', { menu, main: await page.getByRole('main').innerText() })
  expect(menu).not.toContain('New workflow')
  await expect(page.getByRole('main')).toContainText('Only Operators set up workflows.')
  await expect(page.getByLabel('What should happen?')).toHaveCount(0)
  await context.close()
})

test('@perf ten Plan it presses with the mock model, each timed to step 2 showing its rows', async ({ browser }) => {
  test.setTimeout(300_000)
  const samples: number[] = []
  const page = await openNew(browser)
  for (let press = 0; press < PRESSES; press += 1) {
    await page.goto('/new')
    await expect(heading(page)).toHaveText(stepHeading(1, 'Describe it'))
    await page.getByLabel('What should happen?').fill(FOLLOW_UP)
    const ms = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          const button = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Plan it')
          const started = performance.now()
          const seen = () => document.querySelector('[aria-label="What I understood"] li') !== null
          new MutationObserver((_, watch) => {
            if (!seen()) return
            watch.disconnect()
            resolve(performance.now() - started)
          }).observe(document.body, { childList: true, subtree: true })
          button?.click()
        }),
    )
    samples.push(ms)
  }
  save('perf', 'plan-head.json', { target: TARGET, samples })
  await page.context().close()
})

test('@review-video-setup the mock model answers the Planner', async () => {
  await connectMockModel(BASE_URL)
})

test('@review-video alice sets up the follow-up ticket workflow and test runs it, and bob says yes', async ({ browser }) => {
  test.setTimeout(400_000)
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
  await context.addInitScript(() => {
    if (!window.localStorage.getItem('portal.dev-user')) window.localStorage.setItem('portal.dev-user', 'alice')
  })
  const page = await context.newPage()
  const video = page.video()
  const started = Date.now()
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  await page.waitForTimeout(1_500)
  await mainMenu(page).getByRole('link', { name: 'New workflow' }).click()
  await page.getByLabel('What should happen?').pressSequentially(FOLLOW_UP, { delay: 12 })
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: 'Plan it' }).click()
  await expect(planRegion(page)).toContainText('Changes data, waits for a yes')
  await page.waitForTimeout(3_000)
  await fixRow(page, 'Looks for', 'Bug tickets in MOCK with no update for 14 days')
  await page.waitForTimeout(2_500)
  await throughToReview(page, 'Follow up stale bug tickets')
  await page.waitForTimeout(3_000)
  await page.getByRole('button', { name: 'Turn it on' }).click()
  await expect(heading(page)).toHaveText('Your workflow is on')
  await page.waitForTimeout(2_500)
  await page.getByRole('button', { name: 'Do a test run now' }).click()
  await expect(page.getByRole('main')).toContainText(/waiting for a yes|Waiting for/i, { timeout: 120_000 })
  await page.waitForTimeout(2_000)
  await page.getByRole('button', { name: 'Test controls' }).click()
  await page.getByRole('region', { name: 'Test controls' }).getByRole('button', { name: 'Bob' }).click()
  await page.getByRole('button', { name: 'Test controls' }).click()
  await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible({ timeout: 60_000 })
  await page.waitForTimeout(2_000)
  await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
  await expect(page.getByRole('main')).toContainText(/created in Jira|Done/, { timeout: 120_000 })
  await page.waitForTimeout(Math.max(3_000, 40_000 - (Date.now() - started)))
  await context.close()
  await video?.saveAs(path.join(EVID, 'p13-review.webm'))
})
