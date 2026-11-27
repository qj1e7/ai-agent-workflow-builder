import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { connectMockModel } from './support/settings'
import { setMockGithubMode, type Backend } from './support/stack'
import { expect, test } from './support/test'
import { decline, devContext, OUT, shot, showRun } from './support/ui'

/**
 * The side panel (spec 3.3, 3.4, ADR 0043): an item opened from a card in the chat shows beside it, one at a time, with More
 * details and Close. At 900 px and narrower it covers the window. Matches SHELL-panel, SHELL-more, APPR-panel,
 * RUN-retry-panel, RUN-retry-from-chat, FIX-open-software and FIX-wide in checks/paths-v4.cjs.
 */

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

const box = (page: Page) => page.getByLabel('Ask, or describe a task')
const thread = (page: Page) => page.getByRole('list', { name: 'Conversation with the Planner' })
const newest = (page: Page) => thread(page).locator(':scope > li').last()
const panel = (page: Page) => page.locator('#side-panel')
const heading = (page: Page) => page.locator('#side-panel-h')

/** Each row's id and its words, in the order shown, so a list in the chat can be held against its page. */
const rowWords = (rows: Locator) =>
  rows.evaluateAll((els) => els.map((el) => [el.getAttribute('data-workflow-id') ?? el.getAttribute('data-software-id') ?? '', (el as HTMLElement).innerText.replace(/\s+/g, ' ').trim()]))

/** Each workflow row's id, name and state, in the order shown. The page draws a row as a table row and the chat as a line, so these are what they share. */
const rowFacts = (rows: Locator) =>
  rows.evaluateAll((els) => els.map((el) => [el.getAttribute('data-workflow-id') ?? '', el.querySelector('b')?.textContent?.trim() ?? '', el.querySelector('span[data-life]')?.textContent?.trim() ?? '']))

async function ask(page: Page, text: string): Promise<void> {
  await box(page).fill(text)
  await box(page).press('Enter')
  await expect(newest(page)).toHaveAttribute('data-answer', 'true')
}

/** While chatting the page never scrolls, only the conversation and the panel do (#app stays put). */
const pageScroll = (page: Page) =>
  page.evaluate(() => [document.scrollingElement?.scrollTop ?? 0, document.getElementById('root')?.scrollTop ?? 0, document.getElementById('main')?.scrollTop ?? 0])

const AGENTS = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }]

async function newWorkflow(backend: Backend, user: string, name: string): Promise<string> {
  const made = await backend.post<{ use_case_id: string }>(user, '/api/v1/agent-use-cases', { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: AGENTS }, undefined, [201])
  return made.use_case_id
}

/** Workflows whose runs stop because GitHub doesn't answer, one per name. The platform says each can be retried. */
async function stoppedRuns(backend: Backend, names: readonly string[]): Promise<string[]> {
  const ids = await Promise.all(names.map((name) => newWorkflow(backend, 'alice', name)))
  try {
    await setMockGithubMode('unavailable')
    const runs = await Promise.all(ids.map((id) => backend.checkNow('alice', id)))
    for (const run of runs) await backend.waitForState(run, ['failed'], 150_000)
    return runs
  } finally {
    await setMockGithubMode('ok')
  }
}

/** A run Carol set up and started, so Alice may decide it. */
async function carolsWaitingRun(backend: Backend): Promise<string> {
  const run = await backend.checkNow('carol', await newWorkflow(backend, 'carol', `Carol’s check ${randomUUID().slice(0, 6)}`))
  await backend.waitForState(run, ['awaiting_approval'])
  return run
}

async function expectBesideOrCovering(page: Page, width: number): Promise<void> {
  const viewport = page.viewportSize()?.width ?? width
  const panelBox = await panel(page).boundingBox()
  if (width > 900) {
    await expect(panel(page)).toHaveAttribute('role', 'complementary')
    await expect(thread(page), 'the chat stays beside the panel').toBeVisible()
    expect(panelBox && panelBox.width < viewport / 2, 'the panel leaves the chat most of the width').toBe(true)
  } else {
    await expect(panel(page)).toHaveAttribute('role', 'dialog')
    await expect(panel(page)).toHaveAttribute('aria-modal', 'true')
    expect(panelBox?.width, 'the panel covers the window').toBe(viewport)
    await expect(page.locator('[data-chat] > [inert]'), 'the chat behind it waits').toHaveCount(1)
  }
}

for (const width of [1280, 900]) {
  test(`SHELL-panel: a card’s workflow opens in the side panel, Escape and Close put it back with focus on what opened it, at ${String(width)} px`, async ({ browser, backend }, info) => {
    const name = `Side panel ${randomUUID().slice(0, 6)}`
    await newWorkflow(backend, 'alice', name)
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.setViewportSize({ width, height: width > 900 ? 900 : 844 })
    await page.goto('/')
    await ask(page, `Is ${name} running?`)
    const opener = newest(page).getByRole('button', { name, exact: true })
    await opener.click()

    await expect(heading(page)).toHaveText(name)
    await expect(heading(page), 'focus goes to the panel’s heading').toBeFocused()
    await expect(panel(page)).toContainText('Last run')
    await expect(panel(page), 'a workflow that runs only on Run now has no Next run row').not.toContainText('Next run')
    await expect(panel(page).getByRole('link', { name: 'More details' })).toHaveAttribute('href', /^\/workflows\/uc_/)
    await expectBesideOrCovering(page, width)
    await expectAccessible(page, path.join(OUT, 'axe'), `side-panel-workflow-${String(width)}`)
    if (width <= 900) {
      for (let press = 0; press < 6; press += 1) {
        await page.keyboard.press('Tab')
        expect(await page.evaluate(() => document.getElementById('side-panel')?.contains(document.activeElement)), 'Tab stays inside the open panel').toBe(true)
      }
    }
    await shot(page, info, `r3-side-panel-workflow-${String(width)}`)

    await page.keyboard.press('Escape')
    await expect(panel(page), 'Escape closes it').toHaveCount(0)
    await expect(opener, 'focus goes back to what opened it').toBeFocused()

    await opener.click()
    await panel(page).getByRole('button', { name: 'Close' }).click()
    await expect(panel(page)).toHaveCount(0)
    await expect(opener).toBeFocused()
    expect(await pageScroll(page), '#app has not scrolled').toEqual([0, 0, 0])
    assertClean(watch)
    await context.close()
  })
}

test('FIX-wide: on a wide screen the chat sits next to its side panel', async ({ browser, backend }) => {
  const name = `Wide panel ${randomUUID().slice(0, 6)}`
  await newWorkflow(backend, 'alice', name)
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  for (const width of [1920, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/')
    await ask(page, `Is ${name} running?`)
    await newest(page).getByRole('button', { name, exact: true }).click()
    const gap = await page.evaluate(() => {
      const chat = document.querySelector('[aria-label="Conversation"] > div')?.getBoundingClientRect()
      const beside = document.getElementById('side-panel')?.getBoundingClientRect()
      return chat && beside ? Math.round(beside.left - chat.right) : null
    })
    expect(gap, `the chat and the panel sit together at ${String(width)} px`).not.toBeNull()
    expect(gap ?? -1).toBeGreaterThanOrEqual(0)
    expect(gap ?? 99).toBeLessThanOrEqual(24)
  }
  await context.close()
})

test('a stopped run: SHELL-more, RUN-retry-from-chat and RUN-retry-panel, at 1280 and 900 px', async ({ browser, backend }, info) => {
  const tag = randomUUID().slice(0, 6)
  const names = [`Stops first ${tag}`, `Stops second ${tag}`]
  const [first, second] = await stoppedRuns(backend, names)
  if (!first || !second) throw new Error('two stopped runs')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')

  await ask(page, `Why did ${names[0] ?? ''} stop?`)
  const card = newest(page)
  await showRun(page, card.locator(`[data-opens="run:${first}"]`))
  await expect(panel(page)).toContainText(/What happened[\s\S]*Affected[\s\S]*Safe to retry[\s\S]*Retry/)
  await expect(card.getByRole('button', { name: 'Retry', exact: true }), 'a flow shows once: the card gives its Retry to the panel').toHaveCount(0)
  await expect(card.locator(`[data-opens="run:${first}"]`), '…and its See the run').toHaveCount(0)
  await shot(page, info, 'r3-side-panel-run-1280')

  await panel(page).getByRole('link', { name: 'More details' }).click()
  await expect(page).toHaveURL(new RegExp(`/runs/${first}$`))
  await expect(page.getByRole('link', { name: 'Back to the chat' })).toBeVisible()
  await expect(thread(page), 'the chat is not on a full page').toHaveCount(0)
  await page.getByRole('main').getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('main').getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByRole('link', { name: 'Back to the chat' }), 'Back still goes to the chat after Retry').toBeVisible()
  await page.getByRole('link', { name: 'Back to the chat' }).click()
  await expect(panel(page), 'the panel is still there on return').toBeVisible()
  await expect(panel(page).getByRole('button', { name: 'Retry', exact: true }), 'the panel shows the retried run').toHaveCount(0, { timeout: 15_000 })
  await expect(card, 'the card drawn again keeps its run, though the retry took it off the stopped list').toContainText(names[0] ?? '')
  await expect(card).not.toContainText('Nothing has stopped right now.')
  await panel(page).getByRole('button', { name: 'Close' }).click()

  await page.setViewportSize({ width: 900, height: 844 })
  await ask(page, `Why did ${names[1] ?? ''} stop?`)
  await showRun(page, newest(page).locator(`[data-opens="run:${second}"]`))
  await expectBesideOrCovering(page, 900)
  await expect(panel(page).getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await expect(heading(page), 'focus is on the heading in the dialog').toBeFocused()
  await shot(page, info, 'r3-side-panel-run-900')
  await panel(page).getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(panel(page).getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0, { timeout: 15_000 })
  await expect(panel(page), 'the panel stays open on what changed').toBeVisible()
  await expect(heading(page), 'focus is on the panel’s heading').toBeFocused()
  expect(await pageScroll(page), '#app has not scrolled').toEqual([0, 0, 0])
  assertClean(watch)
  await context.close()
})

test('the run card moves in place from the stream: stopped, retrying, waiting for a yes, then done, as one element', async ({ browser, backend }, info) => {
  const name = `Moves in place ${randomUUID().slice(0, 6)}`
  const [runId] = await stoppedRuns(backend, [name])
  if (!runId) throw new Error('a stopped run')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await ask(page, `Why did ${name} stop?`)
  await expect(panel(page), 'on a wide screen the run opens beside the chat by itself').toBeVisible({ timeout: 20_000 })
  await panel(page).getByRole('button', { name: 'Close' }).click()
  await expect(panel(page), 'closed, so the card offers its own Retry again').toHaveCount(0)
  const card = newest(page).locator('section').filter({ has: page.getByRole('heading', { name, exact: true }) })
  const pill = card.locator('[data-run-pill]')
  await expect(pill).toHaveText('Stopped', { timeout: 15_000 })
  await card.evaluate((element) => {
    const seen: string[] = []
    const note = () => {
      const said = [element.querySelector('[data-run-pill]')?.textContent ?? '', ...Array.from(element.querySelectorAll('dd'), (dd) => dd.textContent ?? '')].join(' | ')
      if (seen.at(-1) !== said) seen.push(said)
    }
    note()
    new MutationObserver(note).observe(element, { subtree: true, childList: true, characterData: true })
    Object.assign(window, { runCard: { element, seen } })
  })

  await card.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(pill, 'the same card waits for approval after the retry').toHaveText('Waiting for approval', { timeout: 90_000 })
  const approvalId = await backend.approvalIdOf(runId)
  const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest }, undefined, [201])
  await expect(pill, '…and is done once Bob said yes').toHaveText('Done', { timeout: 60_000 })
  await shot(page, info, 'c3-run-card-done-1280')

  const { same, seen } = await page.evaluate(() => {
    const { element, seen } = (window as unknown as { runCard: { element: Element; seen: string[] } }).runCard
    return { same: element.isConnected && element.querySelector('[data-run-pill]')?.textContent === 'Done', seen }
  })
  expect(same, 'the card that stopped is the element that is done: it moved in place, with no remount').toBe(true)
  const STAGES: readonly (readonly [string, RegExp])[] = [
    ['stopped', /^Stopped/],
    ['retrying', /Retrying after a short wait/],
    ['waiting', /^Waiting for approval/],
    ['writing', /approved\. Creating the ticket/],
    ['done', /^Done/],
  ]
  const order = seen
    .flatMap((said) => STAGES.filter(([, words]) => words.test(said)).map(([stage]) => stage))
    .filter((stage, index, all) => stage !== all[index - 1])
  // The write can land in the same moment as the yes, so the card may never draw "Creating the ticket" on its own.
  expect([['stopped', 'retrying', 'waiting', 'done'], ['stopped', 'retrying', 'waiting', 'writing', 'done']], `the card went through each stage in order: ${seen.join(' / ')}`).toContainEqual(order)
  assertClean(watch)
  await context.close()
})

test('a Retry in the chat’s run card that another Operator beat says who, in the chat’s message, and keeps focus on the card (issue 158)', async ({ browser, backend }, info) => {
  const name = `Beaten to it ${randomUUID().slice(0, 6)}`
  const [runId] = await stoppedRuns(backend, [name])
  if (!runId) throw new Error('a stopped run')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await ask(page, `Why did ${name} stop?`)
  await expect(panel(page), 'on a wide screen the run opens beside the chat by itself').toBeVisible({ timeout: 20_000 })
  await panel(page).getByRole('button', { name: 'Close' }).click()
  const card = newest(page).locator('section').filter({ has: page.getByRole('heading', { name, exact: true }) })
  await expect(card.locator('[data-run-pill]')).toHaveText('Stopped', { timeout: 15_000 })
  await page.route(`**/api/v1/runs/${runId}/retry`, async (route) => {
    await backend.post('carol', `/api/v1/runs/${runId}/retry`, undefined, undefined, [202])
    await backend.waitToLeave(runId, 'failed', 60_000)
    await route.continue()
  })
  const answered = page.waitForResponse((response) => response.url().endsWith(`/api/v1/runs/${runId}/retry`), { timeout: 90_000 })
  await card.getByRole('button', { name: 'Retry', exact: true }).click()
  expect((await answered).status(), 'Carol retried it first, so the platform refuses Alice’s press').toBe(409)

  const said = 'Carol already retried this run.'
  await expect(page.getByRole('status').filter({ hasText: said }), 'a screen reader hears who retried it').toHaveText(said)
  await expect(page.locator('[aria-hidden="true"]', { hasText: said }), 'and the chat shows it').toBeVisible()
  await expect(card.getByRole('heading', { name, exact: true }), 'focus goes to the card’s title, which stays as the run moves on').toBeFocused()
  await shot(page, info, 'i158-card-retried-first')
  await expect(card.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
  assertClean(watch)
  await context.close()
})

async function openRequest(page: Page, runId: string): Promise<Locator> {
  await ask(page, 'What needs me?')
  const opener = newest(page).locator(`[data-opens="approval:${runId}"]`)
  await opener.click()
  return opener
}

test('APPR-panel: Alice declines in the side panel, focus goes to its heading, the page stays put, and the card follows', async ({ browser, backend }, info) => {
  const runId = await carolsWaitingRun(backend)
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await openRequest(page, runId)
  await expect(panel(page), 'exactly what will be written, from the request').toContainText(/This run wants to create 1 Jira ticket in MOCK:[\s\S]*Where[\s\S]*Summary/)
  await expect(heading(page), 'focus is on the heading once the request has loaded').toBeFocused()
  await expect(panel(page), 'the AI’s summary and Why you wait for the page').not.toContainText(/Summary by AI|Why you/)
  await expectAccessible(page, path.join(OUT, 'axe'), 'side-panel-approval-1280')
  await shot(page, info, 'r3-side-panel-approval-1280')
  await decline(panel(page), 'Not needed this time')
  await expect(page.getByRole('status').filter({ hasText: 'Declined. Nothing was written. Reason: Not needed this time.' }), 'a message at the bottom tells Alice').toHaveCount(1)
  await expect(heading(page), 'focus is on the panel’s heading').toBeFocused()
  await expect(panel(page), 'the panel stays on the request, with its record').toContainText(/Declined by Alice (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}: not needed this time\. Nothing was written\./, { timeout: 15_000 })
  await expect(panel(page).locator('[data-run-pill]'), 'its pill says Declined in words').toHaveText('Declined')
  await expect(panel(page), 'a declined record never says created').not.toContainText(/created/i)
  await shot(page, info, 'r12-panel-declined-by-alice-1280')
  expect(await pageScroll(page), '#app has not scrolled').toEqual([0, 0, 0])
  await panel(page).getByRole('button', { name: 'Close' }).click()
  await expect(newest(page).locator(`[data-opens="approval:${runId}"]`), 'the card in the chat no longer waits for a yes').toHaveCount(0, { timeout: 20_000 })
  assertClean(watch)
  await context.close()
})

/**
 * A declined test run needed a workflow on the shared run workflow, and the Software watchlist was the last one the harness could
 * make. The watchlist now runs as its own n8n workflow, where a test run stops at the gate and asks nobody (ENGINE-PLAN 2.3.3), so
 * nobody can decline it.
 */
test('a test run of the Software watchlist stops before the yes, asks nobody and writes nothing', async ({ backend }) => {
  const useCaseId = await backend.freshWatchlist('alice')
  const started = await backend.post<{ run_id: string }>('alice', `/api/v1/use-cases/${useCaseId}/runs`, { test: true }, { 'Idempotency-Key': randomUUID() }, [201])
  const run = await backend.waitForState(started.run_id, ['succeeded'])
  expect(run.outcome, 'it passed at the gate').toBe('test_passed')
  const { events } = await backend.get<{ events: { kind: string }[] }>('alice', `/api/v1/runs/${started.run_id}/events?after=0`)
  expect(events.map((event) => event.kind), 'nobody was asked').not.toContain('approval_requested')
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === started.run_id), 'nothing was written').toEqual([])
})

test('APPR-panel at 900 px: Alice approves in the full-window panel, and its record shows the write going on', async ({ browser, backend }, info) => {
  const runId = await carolsWaitingRun(backend)
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 900, height: 844 })
  await page.goto('/')
  await openRequest(page, runId)
  await expectBesideOrCovering(page, 900)
  await expect(panel(page).getByRole('button', { name: /^Approve/ })).toBeVisible()
  await expect(heading(page), 'focus is on the heading in the dialog').toBeFocused()
  await expectAccessible(page, path.join(OUT, 'axe'), 'side-panel-approval-900')
  await shot(page, info, 'r3-side-panel-approval-900')
  await panel(page).getByRole('button', { name: /^Approve/ }).click()
  await expect(heading(page)).toBeFocused()
  await expect(panel(page).getByRole('button', { name: /^Approve/ })).toHaveCount(0)
  await expect(panel(page)).toContainText(/Approved by Alice (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}\. (Creating the ticket…|MOCK-\d+ created\.)/, { timeout: 30_000 })
  expect(await pageScroll(page)).toEqual([0, 0, 0])
  await context.close()
})

test('FIX-open-software: a software already on the watchlist opens in the side panel, with More details to its row', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await ask(page, 'Monitor LangGraph releases on the watchlist')
  await newest(page).getByRole('button', { name: 'Open it' }).click()
  await expect(heading(page)).toHaveText('LangGraph')
  await expect(panel(page), 'with no schedule, nothing checks it on its own').toContainText(/Watching[\s\S]*Checked by\s*Not checked automatically/)
  await expectAccessible(page, path.join(OUT, 'axe'), 'side-panel-software-1280')
  await shot(page, info, 'r3-side-panel-software-1280')
  await panel(page).getByRole('link', { name: 'More details' }).click()
  await expect(page).toHaveURL(/\?software=[^&]+$/)
  await expect(page.getByRole('link', { name: 'Back to the chat' })).toBeVisible()
  await context.close()
})

test('one Escape closes one thing: an editor in a card beside the panel first, then the panel', async ({ browser, backend }) => {
  const name = `Escape order ${randomUUID().slice(0, 6)}`
  await newWorkflow(backend, 'alice', name)
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await ask(page, `Is ${name} running?`)
  await newest(page).getByRole('button', { name, exact: true }).click()
  await ask(page, 'Find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them')
  await newest(page).getByRole('button', { name: 'Every weekday', exact: true }).click()
  await newest(page).getByRole('button', { name: 'Another time', exact: true }).click()
  await newest(page).getByLabel('Time, Singapore').fill('15:00')
  await page.keyboard.press('Escape')
  await expect(newest(page).getByLabel('How often'), 'the editor takes the first Escape').toHaveCount(0)
  await expect(panel(page), 'the panel stays').toBeVisible()
  await page.keyboard.press('Escape')
  await expect(panel(page), 'the next Escape closes the panel').toHaveCount(0)
  await context.close()
})

test('narrowing the window to 900 px with the panel open moves focus from the chat into the panel', async ({ browser, backend }) => {
  const name = `Narrowing ${randomUUID().slice(0, 6)}`
  await newWorkflow(backend, 'alice', name)
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await ask(page, `Is ${name} running?`)
  await newest(page).getByRole('button', { name, exact: true }).click()
  await box(page).focus()
  await page.setViewportSize({ width: 900, height: 844 })
  await expect(panel(page)).toHaveAttribute('role', 'dialog')
  await expect(heading(page), 'the chat behind the dialog waits, so focus moves to the panel').toBeFocused()
  await context.close()
})

/** Jira stops answering, so a connection needs Alice. The returned function puts it right again. */
async function jiraDown(backend: Backend): Promise<() => Promise<void>> {
  const answering = (on: boolean) => backend.post('alice', '/api/v1/dev/practice-jira/answering', { answering: on })
  await answering(false)
  await backend.post('alice', '/api/v1/settings/connections/jira/check')
  return async () => {
    await answering(true)
    await backend.post('alice', '/api/v1/settings/connections/jira/check')
  }
}

async function platformNeeds(backend: Backend, user: string): Promise<number> {
  const home = await backend.get<{ approvals_total: number; stopped_total: number; declined_total: number; questions_for_me_total: number; confirmations: unknown[]; connections: unknown[]; addresses: unknown[]; replied: unknown[] }>(user, '/api/v1/home')
  return home.approvals_total + home.stopped_total + home.declined_total + home.questions_for_me_total + home.confirmations.length + home.connections.length + home.addresses.length + home.replied.length
}

const strip = (page: Page) => page.getByRole('region', { name: 'Needs you', exact: true })

/** Show more in the panel by keyboard: focus stays on it while there is more, the count is read out, and focus lands on the first new row at the end. */
async function showMoreByKeyboard(page: Page, total: number): Promise<void> {
  const rows = panel(page).locator('li[data-home-item]')
  const line = panel(page).getByRole('status').filter({ hasText: /^Showing / })
  const more = panel(page).getByRole('button', { name: 'Show more', exact: true })
  await expect(line).toHaveText(`Showing ${String(await rows.count())} of ${String(total)}.`)
  await more.focus()
  while ((await more.count()) > 0) {
    const before = await rows.evaluateAll((items) => items.map((item) => item.getAttribute('data-home-item')))
    await page.keyboard.press('Enter')
    await expect.poll(() => rows.count(), { message: 'the next page joins the same list' }).toBeGreaterThan(before.length)
    const now = await rows.count()
    if (now < total) {
      await expect(more, 'focus stays on Show more while there is more').toBeFocused()
      await expect(line, 'the new count is read out').toHaveText(`Showing ${String(now)} of ${String(total)}.`)
      continue
    }
    await expect(more).toHaveCount(0)
    await expect(line, 'the last count is read out').toHaveText(`Showing all ${String(total)}.`)
    const landed = await page.evaluate(() => document.activeElement?.closest('li[data-home-item]')?.getAttribute('data-home-item') ?? null)
    expect(landed, 'focus moves to a row that was not there before').not.toBeNull()
    expect(before, 'focus moves to a new row').not.toContain(landed)
  }
}

for (const width of [1440, 390]) {
  test(`PANEL-needs at ${String(width)} px: N more opens Needs you beside the chat, a row opens beside it with Back, More details is the full page, and Escape puts focus on N more`, async ({ browser, backend }, info) => {
    const tag = randomUUID().slice(0, 6)
    const [stop] = await stoppedRuns(backend, [`Needs panel ${tag}`])
    if (!stop) throw new Error('a stopped run')
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.setViewportSize({ width, height: width > 900 ? 900 : 844 })
    await page.goto('/')
    await ask(page, 'What can you do?')
    const total = await platformNeeds(backend, 'alice')
    expect(total).toBeGreaterThan(1)
    const more = strip(page).getByRole('button', { name: `${String(total - 1)} more that need you` })
    await expect(more, 'the strip’s N more is a button that opens the panel').toBeVisible()

    await more.click()
    await expect(heading(page)).toHaveText('Needs you')
    await expect(heading(page), 'focus goes to the panel’s heading').toBeFocused()
    const first = await panel(page).locator('li[data-home-item]').count()
    expect(first, 'the panel lists the first page of needs').toBeGreaterThan(1)
    if (first < total) await showMoreByKeyboard(page, total)
    const rows = await panel(page).locator('li[data-home-item]').count()
    expect(rows, 'the panel holds every need, and the strip’s N more plus one is the count').toBe(total)
    await expect(panel(page).getByRole('heading', { name: 'Do now' })).toBeVisible()
    await expect(panel(page).getByRole('link', { name: 'More details' })).toHaveAttribute('href', '/workflows')
    await expectBesideOrCovering(page, width)
    await expectAccessible(page, path.join(OUT, 'axe'), `side-panel-needs-${String(width)}`)
    await shot(page, info, `c4-needs-${String(width)}`)

    await panel(page).locator(`li[data-home-item="stopped:${stop}"] button`).click()
    await expect(panel(page)).toContainText(/Safe to retry/)
    const back = panel(page).getByRole('button', { name: 'Needs you', exact: true })
    await expect(back, 'Back names the list it returns to').toBeVisible()
    await back.click()
    await expect(heading(page)).toHaveText('Needs you')
    await expect(panel(page).locator('li[data-home-item]')).toHaveCount(rows)

    await panel(page).locator(`li[data-home-item="stopped:${stop}"] button`).click()
    await panel(page).getByRole('link', { name: 'More details' }).click()
    await expect(page).toHaveURL(new RegExp(`/runs/${stop}$`))
    await expect(thread(page), 'the second click is the full page, with the chat gone').toHaveCount(0)
    await page.getByRole('link', { name: 'Back to the chat' }).click()
    await expect(panel(page), 'the panel is as it was on return').toBeVisible()

    // The panel listens for Escape from an effect after it is drawn, so a key pressed the instant it reappears can come first.
    await expect(async () => {
      await page.keyboard.press('Escape')
      await expect(panel(page)).toHaveCount(0, { timeout: 1_000 })
    }, 'Escape closes the panel').toPass({ timeout: 10_000 })
    await expect(strip(page).getByRole('button', { name: /more that need you$/ }), 'Escape puts focus back on what opened the panel').toBeFocused()
    expect(await pageScroll(page), '#app has not scrolled').toEqual([0, 0, 0])
    assertClean(watch)
    await repair()
    await context.close()
  })
}

for (const width of [1440, 390]) {
test(`PANEL-connection at ${String(width)} px: a connection that needs Alice opens beside the chat in the platform’s words, and sends her to Settings`, async ({ browser, backend }, info) => {
  const repair = await jiraDown(backend)
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width, height: width > 900 ? 900 : 844 })
  await page.goto('/')
  await ask(page, 'What needs me?')
  await newest(page).locator('[data-opens="connection:jira"]').click()
  await expect(heading(page)).toHaveText('Jira')
  await expect(panel(page)).toContainText('Connection')
  await expect(panel(page)).toContainText('Jira is not answering.')
  await expect(panel(page).getByRole('link', { name: 'See it in Settings' })).toHaveAttribute('href', '/settings?tab=connections')
  await expect(panel(page)).not.toContainText('Asked the admin')
  await shot(page, info, `c4-connection-${String(width)}`)
  await repair()
  await context.close()
})
}

test('AUTO-open: on a wide screen an answer about one stopped run shows it beside the chat by itself, without moving focus, and on a narrow one it waits for Open', async ({ browser, backend }, info) => {
  const tag = randomUUID().slice(0, 6)
  const names = [`Auto wide ${tag}`, `Auto narrow ${tag}`]
  const [wide, narrow] = await stoppedRuns(backend, names)
  if (!wide || !narrow) throw new Error('two stopped runs')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await ask(page, `Why did ${names[0] ?? ''} stop?`)
  await expect(panel(page), 'the run opened beside the chat at once').toBeVisible({ timeout: 20_000 })
  await expect(panel(page)).toContainText(/Safe to retry/)
  await expect(heading(page), 'it did not take focus').not.toBeFocused()
  await shot(page, info, 'c4-auto-open-1440')
  await box(page).fill('and the other one')
  await page.keyboard.press('Escape')
  await expect(panel(page), 'Escape in the box closes the panel').toHaveCount(0)
  await expect(box(page), 'nothing the person pressed opened it, so focus stays in the box').toBeFocused()
  await expect(box(page)).toHaveValue('and the other one')
  await ask(page, 'What can you do?')
  await expect(panel(page), 'a closed panel is not opened again by a later answer').toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await ask(page, `Why did ${names[1] ?? ''} stop?`)
  await expect(panel(page), 'on a narrow screen only the card shows').toHaveCount(0)
  await newest(page).locator(`[data-opens="run:${narrow}"]`).click()
  await expect(panel(page)).toHaveAttribute('role', 'dialog')
  await context.close()
})

for (const width of [1440, 390]) {
test(`PANEL-lists at ${String(width)} px: See all workflows and See the watchlist open the lists beside the chat, a row opens beside them with Back, and More details goes to the page`, async ({ browser, backend }, info) => {
  const tag = randomUUID().slice(0, 6)
  for (let n = 0; n < 6; n += 1) await newWorkflow(backend, 'alice', `List panel ${tag} ${String(n)}`)
  await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.setViewportSize({ width, height: width > 900 ? 900 : 844 })
  await page.goto('/workflows')
  await expect(page.getByRole('list', { name: 'Workflows' }).locator('li[data-workflow-id]').first()).toBeVisible()
  const workflowsPage = await rowFacts(page.getByRole('list', { name: 'Workflows' }).locator('li[data-workflow-id]'))
  await page.goto('/software')
  await expect(page.locator('main li[data-software-id]').first()).toBeVisible()
  const watchlistPage = await rowWords(page.locator('main li[data-software-id]'))
  await page.goto('/')
  await ask(page, 'Check my workflows')
  await expect(newest(page).locator('li[data-workflow-id]'), 'the card shows five').toHaveCount(5)
  await newest(page).getByRole('button', { name: 'See all workflows' }).click()
  await expect(heading(page)).toHaveText('Workflows')
  await expect(panel(page).locator('li[data-workflow-id]').nth(5), 'the panel lists the rest').toBeVisible()
  expect(await rowFacts(panel(page).locator('li[data-workflow-id]')), 'each row names the workflow and its state as its row on Workflows does, in the same order').toEqual(workflowsPage)
  await expect(panel(page).getByRole('link', { name: 'More details' })).toHaveAttribute('href', '/workflows')
  await shot(page, info, `c4-workflows-${String(width)}`)
  await panel(page).locator('li[data-workflow-id] button').first().click()
  await expect(panel(page).getByRole('button', { name: 'Workflows', exact: true }), 'Back names the list').toBeVisible()
  await panel(page).getByRole('button', { name: 'Workflows', exact: true }).click()
  await expect(heading(page)).toHaveText('Workflows')
  await panel(page).getByRole('button', { name: 'Close' }).click()

  await page.getByRole('group', { name: 'Suggestions' }).getByRole('button', { name: 'Which software is behind?' }).click()
  await expect(newest(page), 'it answers at once from the watchlist').toContainText(/\d+ (has|have) a newer version/)
  await newest(page).getByRole('button', { name: 'See the watchlist' }).click()
  await expect(heading(page)).toHaveText('Watchlist')
  await expect(panel(page).getByRole('link', { name: 'More details' })).toHaveAttribute('href', /^\/workflows\/[^/?]+$/)
  expect(await rowWords(panel(page).locator('li[data-software-id]')), 'each row says what its row on the Watchlist says, urgent first').toEqual(watchlistPage)
  await shot(page, info, `c4-watchlist-${String(width)}`)
  const first = panel(page).locator('li[data-software-id]').first()
  const name = await first.locator('b').innerText()
  const pill = await first.locator('span[class*="pill"]').innerText()
  await first.getByRole('button').click()
  await expect(heading(page)).toHaveText(name)
  await expect(panel(page).getByRole('button', { name: 'Watchlist', exact: true })).toBeVisible()
  await expect(panel(page), 'the software says the state its row said').toContainText(pill)
  await expect(panel(page)).toContainText('Checked by')
  assertClean(watch)
  await context.close()
})
}

for (const width of [1440, 390]) {
  test(`PANEL-approval at ${String(width)} px: a request opens beside the chat as an approval, in the sketch’s shape`, async ({ browser, backend }, info) => {
    const runId = await carolsWaitingRun(backend)
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.setViewportSize({ width, height: width > 900 ? 900 : 844 })
    await page.goto('/')
    await openRequest(page, runId)
    await expect(panel(page)).toContainText(/This run wants to create 1 Jira ticket in MOCK:/, { timeout: 20_000 })
    await expect(panel(page).getByRole('button', { name: 'Decline' })).toBeVisible()
    await shot(page, info, `c4-approval-${String(width)}`)
    await context.close()
  })
}

for (const width of [1440, 390]) {
  test(`Bob declines at ${String(width)} px: what waits for him is the request as its card, beside the chat, and he declines with a reason, which the panel and the card both keep`, async ({ browser, backend }, info) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const phone = width === 390
    const context = await devContext(browser, 'bob', { reducedMotion: true, phone })
    const page = await context.newPage()
    if (!phone) await page.setViewportSize({ width, height: 900 })
    const watch = watchPage(page)
    await page.goto('/')
    await page.getByRole('group', { name: 'Suggestions' }).getByRole('button', { name: 'What waits for me?' }).click()
    await expect(newest(page)).toHaveAttribute('data-answer', 'true')
    await expect(newest(page).locator('p').first(), 'the sketch’s lead over the cards').toHaveText(/^(This needs|These need) your approval\.$/)
    const opener = newest(page).locator(`[data-opens="approval:${runId}"]`)
    await expect(opener.or(panel(page)).first(), 'on a wide screen one request shows beside the chat by itself').toBeVisible({ timeout: 20_000 })
    if (!(await panel(page).isVisible())) await opener.click()
    const request = panel(page)
    await expect(request).toContainText('This run wants to create 1 Jira ticket in MOCK:')
    await expect(request.locator('[data-run-pill]')).toHaveText('Waiting for approval')
    await expect(request, 'the whole ticket, as it will be written, is one click away').toContainText(/Where\s*Jira project MOCK on the practice Jira\s*Summary\s*Upgrade /)
    await expect(request, 'the panel has the run page’s shape, with no AI summary and no Not checked').not.toContainText(/Summary by AI|Not checked/)
    await expect(request.getByRole('button', { name: /^(Ask Alice|Approve|Decline)$/ }), 'Ask Alice, then Approve, and Decline last').toHaveText(['Ask Alice', 'Approve', 'Decline'])
    await shot(page, info, `c5-bob-request-${String(width)}`)

    await request.getByRole('button', { name: 'Decline', exact: true }).click()
    const why = request.getByRole('group', { name: /^Why\? Optional\. Alice will see it\./ })
    await expect(why.getByRole('button'), 'the quick reasons, then Back, and Decline last').toHaveText(['Not this week', 'Wrong version', 'Needs testing first', 'Back', 'Decline'])
    await expect(why.getByRole('button', { name: 'Not this week' }), 'focus is on the first reason').toBeFocused()
    await why.getByRole('button', { name: 'Not this week' }).click()
    await expectAccessible(page, path.join(OUT, 'axe'), `c5-bob-decline-${String(width)}`)
    await shot(page, info, `c5-bob-why-${String(width)}`)
    expect((await backend.run(runId)).state, 'nothing is decided until the second Decline').toBe('awaiting_approval')
    await why.getByRole('button', { name: 'Decline', exact: true }).click()

    await expect(request, 'the panel keeps the request, with its record').toContainText(/Declined by Bob (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}: not this week\. Nothing was written\./, { timeout: 15_000 })
    await expect(request.locator('[data-run-pill]')).toHaveText('Declined')
    await expect(request.getByRole('button', { name: /^(Approve|Decline|Ask Alice)$/ }), 'nothing is left to decide').toHaveCount(0)
    await expect(request, 'a declined record never says created').not.toContainText(/created/i)
    await shot(page, info, `c5-bob-declined-${String(width)}`)
    await panel(page).getByRole('button', { name: 'Close' }).click()
    const card = newest(page).locator('section', { has: page.locator(`[data-opens="approval:${runId}"]`) })
    await expect(card, 'the card stays in the chat, with what happened').toContainText(/Create 1 Jira ticket\s*Declined[\s\S]*Declined\. Nothing was written\./)
    await expect(card.getByRole('button', { name: 'Review and decide' })).toHaveCount(0)

    const view = await backend.get<{ steps: { status: string; reason: string | null }[] }>('bob', `/api/v1/approvals/${approvalId}`)
    expect(view.steps.map((step) => [step.status, step.reason])).toEqual([['declined', 'Not this week']])
    expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing was written').toEqual([])
    assertClean(watch)
    await context.close()
  })
}
