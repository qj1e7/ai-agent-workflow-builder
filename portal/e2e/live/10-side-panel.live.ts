import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { connectMockModel } from './support/settings'
import { setMockGithubMode, type Backend } from './support/stack'
import { expect, test } from './support/test'
import { decline, devContext, OUT, shot } from './support/ui'

/**
 * The side panel (spec 3.3, 3.4, ADR 0043): an item opened from a card in the chat shows beside it, one at a time, with More
 * details and Close. At 900 px and narrower it covers the window. Matches SHELL-panel, SHELL-more, APPR-panel,
 * RUN-retry-panel, RUN-retry-from-chat, FIX-open-software and FIX-wide in checks/paths-v4.cjs.
 */

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

const box = (page: Page) => page.getByLabel('Ask the Planner about software versions')
const thread = (page: Page) => page.getByRole('list', { name: 'Conversation with the Planner' })
const newest = (page: Page) => thread(page).locator(':scope > li').last()
const panel = (page: Page) => page.locator('#side-panel')
const heading = (page: Page) => page.locator('#side-panel-h')

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
    await ask(page, 'Check my workflows')
    const opener = newest(page).getByRole('button', { name, exact: true })
    await opener.click()

    await expect(heading(page)).toHaveText(name)
    await expect(heading(page), 'focus goes to the panel’s heading').toBeFocused()
    await expect(panel(page)).toContainText(/Last run[\s\S]*Next run/)
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
    await ask(page, 'Check my workflows')
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
  await card.locator(`[data-opens="run:${first}"]`).click()
  await expect(panel(page)).toContainText(/What happened[\s\S]*What was affected[\s\S]*Safe to retry[\s\S]*Retry the run/)
  await expect(heading(page), 'focus is on the heading once the run has loaded').toBeFocused()
  await expect(card.getByRole('button', { name: 'Retry the run' }), 'a flow shows once: the card gives its Retry to the panel').toHaveCount(0)
  await expect(card.locator(`[data-opens="run:${first}"]`), '…and its See the run').toHaveCount(0)
  await shot(page, info, 'r3-side-panel-run-1280')

  await panel(page).getByRole('link', { name: 'More details' }).click()
  await expect(page).toHaveURL(new RegExp(`/runs/${first}$`))
  await expect(page.getByRole('link', { name: 'Back to the chat' })).toBeVisible()
  await expect(thread(page), 'the chat is not on a full page').toHaveCount(0)
  await page.getByRole('main').getByRole('button', { name: 'Retry the run' }).click()
  await expect(page.getByRole('main').getByRole('button', { name: 'Retry the run' })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByRole('link', { name: 'Back to the chat' }), 'Back still goes to the chat after Retry').toBeVisible()
  await page.getByRole('link', { name: 'Back to the chat' }).click()
  await expect(panel(page), 'the panel is still there on return').toBeVisible()
  await expect(panel(page).getByRole('button', { name: 'Retry the run' }), 'the panel shows the retried run').toHaveCount(0, { timeout: 15_000 })
  await panel(page).getByRole('button', { name: 'Close' }).click()

  await page.setViewportSize({ width: 900, height: 844 })
  await ask(page, `Why did ${names[1] ?? ''} stop?`)
  await newest(page).locator(`[data-opens="run:${second}"]`).click()
  await expectBesideOrCovering(page, 900)
  await expect(panel(page).getByRole('button', { name: 'Retry the run' })).toBeVisible()
  await expect(heading(page), 'focus is on the heading in the dialog').toBeFocused()
  await shot(page, info, 'r3-side-panel-run-900')
  await panel(page).getByRole('button', { name: 'Retry the run' }).click()
  await expect(panel(page).getByRole('button', { name: 'Retry the run' })).toHaveCount(0, { timeout: 15_000 })
  await expect(panel(page), 'the panel stays open on what changed').toBeVisible()
  await expect(heading(page), 'focus is on the panel’s heading').toBeFocused()
  expect(await pageScroll(page), '#app has not scrolled').toEqual([0, 0, 0])
  assertClean(watch)
  await context.close()
})

async function openRequest(page: Page, runId: string): Promise<Locator> {
  await ask(page, 'What needs me?')
  const opener = newest(page).locator(`[data-opens="run:${runId}"]`)
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
  await expect(panel(page)).toContainText(/What will change[\s\S]*This is exactly what will be written, and nothing else\.[\s\S]*What happens/)
  await expect(heading(page), 'focus is on the heading once the request has loaded').toBeFocused()
  await expect(panel(page), 'Why, Who asked and Your part wait for the page').not.toContainText(/Who asked|Your part|\bWhy\b/)
  await expectAccessible(page, path.join(OUT, 'axe'), 'side-panel-approval-1280')
  await shot(page, info, 'r3-side-panel-approval-1280')
  await decline(panel(page), 'Not needed this time')
  await expect(page.getByRole('status').filter({ hasText: 'Declined. Nothing was written. Reason: Not needed this time.' }), 'a message at the bottom tells Alice').toHaveCount(1)
  await expect(heading(page), 'focus is on the panel’s heading').toBeFocused()
  await expect(panel(page), 'the panel gives the declined record').toContainText(/Declined\s*Declined by Alice\. Nothing was written\. Reason: Not needed this time\./, { timeout: 15_000 })
  await expect(panel(page), 'its line says nothing was written').toContainText('Nothing written')
  await shot(page, info, 'r12-panel-declined-by-alice-1280')
  expect(await pageScroll(page), '#app has not scrolled').toEqual([0, 0, 0])
  await panel(page).getByRole('button', { name: 'Close' }).click()
  await expect(newest(page).locator(`[data-opens="run:${runId}"]`), 'the card in the chat no longer waits for a yes').toHaveCount(0, { timeout: 20_000 })
  assertClean(watch)
  await context.close()
})

for (const width of [1280, 390]) {
  test(`DECLINED-test-run at ${width} px: Alice’s declined test run is in her Needs you and in the side panel, in the record’s words, with no write`, async ({ browser, backend }, info) => {
    const useCaseId = await newWorkflow(backend, 'alice', `Alice’s test ${randomUUID().slice(0, 6)}`)
    const started = await backend.post<{ run_id: string }>('alice', `/api/v1/use-cases/${useCaseId}/runs`, { test: true }, { 'Idempotency-Key': randomUUID() }, [201])
    const runId = started.run_id
    await backend.waitForState(runId, ['awaiting_approval'])
    const approvalId = await backend.approvalIdOf(runId)
    const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
    await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'decline', digest, reason: 'Something in it is wrong' }, undefined, [201])
    await backend.waitForState(runId, ['rejected'])
    const record = /Declined\s*Declined by Bob\. Nothing was written\. Reason: Something in it is wrong\./

    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.setViewportSize({ width, height: 900 })
    try {
      await page.goto('/workflows')
      const needs = page.getByRole('list', { name: 'Needs you' })
      await expect(needs, 'Needs you says Bob declined it, in the record’s words').toContainText(/Bob declined your test run[\s\S]{0,120}Nothing was written\. Reason: Something in it is wrong\./)
      await shot(page, info, `r12-needs-you-declined-test-alice-${width}`)
      await page.goto('/')
      await openRequest(page, runId)
      await expect(panel(page), 'the side panel gives the state and the record').toContainText(record, { timeout: 15_000 })
      await expect(panel(page), 'and what happens next').toContainText('Something in it is wrong. Change what it does, or run the test again.')
      await expect(panel(page), 'its line says the write did not happen').toContainText('Nothing written')
      await expect(panel(page), 'the panel shows no write').not.toContainText(/created|MOCK-\d/)
      await shot(page, info, `r12-panel-declined-test-alice-${width}`)
      await page.goto(`/runs/${runId}`)
      await page.locator('summary', { hasText: /what each agent did$/ }).click()
      await expect(page.getByRole('list', { name: 'What the agents said' }), 'the run ends with what happens next').toContainText('The run ended. Change what it does, or run the test again.')

      await page.goto('/workflows')
      const item = needs.locator('li').filter({ hasText: 'Bob declined your test run' })
      await expect(item.locator('svg path[d="M6 6l12 12M18 6L6 18"]').first(), 'the row has the X, not the info mark').toBeAttached()
      await item.getByRole('button', { name: 'Do a test run again' }).click()
      await expect(page).toHaveURL(/\/runs\/[^/]+$/)
      const again = page.url().split('/').at(-1) ?? ''
      expect(again, 'a new run started').not.toBe(runId)
      expect((await backend.run(again)).test, 'it is a test run, as last_run says').toBe(true)
      expect((await backend.get<{ use_cases: { use_case_id: string; last_run: { test: boolean } | null }[] }>('alice', '/api/v1/use-cases')).use_cases.find((u) => u.use_case_id === useCaseId)?.last_run?.test).toBe(true)
      await page.goto('/workflows')
      await expect(page.getByText('Bob declined your test run'), 'a new run of the workflow takes it off Needs you').toHaveCount(0)
    } finally {
      await context.close()
      await backend.delete('alice', `/api/v1/use-cases/${useCaseId}`)
    }
  })
}

test('APPR-panel at 900 px: Alice approves in the full-window panel, and it shows the run going on', async ({ browser, backend }, info) => {
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
  await expect(panel(page)).toContainText(/Done|created in Jira|writing now/, { timeout: 30_000 })
  expect(await pageScroll(page)).toEqual([0, 0, 0])
  await context.close()
})

test('FIX-open-software: a software already on the watchlist opens in the side panel, with More details to its row', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice')
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await ask(page, 'Monitor LangGraph releases')
  await newest(page).getByRole('button', { name: 'Open it' }).click()
  await expect(heading(page)).toHaveText('LangGraph')
  await expect(panel(page)).toContainText(/You run\s*1\.2\.14[\s\S]*Newest[\s\S]*Checked by\s*The Version checker/)
  await expectAccessible(page, path.join(OUT, 'axe'), 'side-panel-software-1280')
  await shot(page, info, 'r3-side-panel-software-1280')
  await panel(page).getByRole('link', { name: 'More details' }).click()
  await expect(page).toHaveURL(/\/software\?row=/)
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
  await ask(page, 'Check my workflows')
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
  await ask(page, 'Check my workflows')
  await newest(page).getByRole('button', { name, exact: true }).click()
  await box(page).focus()
  await page.setViewportSize({ width: 900, height: 844 })
  await expect(panel(page)).toHaveAttribute('role', 'dialog')
  await expect(heading(page), 'the chat behind the dialog waits, so focus moves to the panel').toBeFocused()
  await context.close()
})
