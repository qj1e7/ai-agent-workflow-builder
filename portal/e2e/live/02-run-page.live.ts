import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Browser, BrowserContext, Locator, Page, TestInfo } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { tabTo } from '../support/keyboard'
import { assertClean, watchPage } from '../support/test'
import { holdRunAtWork, linkAnimations, runLinks } from './support/runLine'
import { connectMockModel } from './support/settings'
import { setMockGithubMode, type Backend, type WaitingRun } from './support/stack'
import { expect, test } from './support/test'
import { decline, declineReasons, devContext, OUT, shot, showHistory } from './support/ui'

interface ApprovalAnswer {
  actions: { fields: { title: string } }[]
  you_can_decide: boolean
  why_not: string | null
}

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
/** The run's one state pill, beside the workflow's name. */
const state = (page: Page) => page.locator('[data-run-pill]')
/** The plain steps under Run history. Open it first with showHistory. */
const stepLog = (page: Page) => page.getByRole('list', { name: 'Run history', exact: true })
/** The agents' own words, behind Show agent messages. */
const agentMessages = (page: Page) => page.getByRole('list', { name: 'Agent messages', exact: true })
const answer = (page: Page, name: string) => page.locator('dl', { has: page.locator('dt', { hasText: new RegExp(`^${name}$`) }) })
/** A section of the approval, named by its heading: What will be written, or Not checked. */
const part = (scope: Page | Locator, name: string) => scope.getByRole('region', { name, exact: true })
/** The request's own pill, which the run page does not draw: its status is the run's pill in the top line. */
const approvalPill = (scope: Page | Locator) => scope.locator('[data-approval-pill]')
const APPROVE = { name: 'Approve', exact: true } as const
/** Every animation that ends has ended. The dashes marching into a yes that waits loop, as they should. */
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().every((animation) => animation.effect?.getComputedTiming().iterations === Infinity))
const steps = (page: Page) => page.getByRole('list', { name: 'Steps of this run' }).locator('li[data-state]')
/** How visible the green tick on the face above a step is, 0 to 1. */
const faceTick = (step: Locator) => step.locator('[data-face] circle[fill="var(--green)"]').evaluate((circle) => getComputedStyle(circle.parentElement ?? circle).opacity)
/** Under the waiting gate, once the platform says the request is in Teams: who may decide it, never the person whose run it is. */
const sentLine = (page: Page) => page.locator('li[data-state="wait"] [data-sent]')
const SENT_TO_BOB = /^Sent to (.+, )?Bob( and .+|, .+)? in Teams$/

test('alice starts a check; bob opens the waiting run, sees the ticket it will create, approves, and watches it reach Done', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const forBob = await backend.get<ApprovalAnswer>('bob', `/api/v1/approvals/${approvalId}`)
  expect(forBob.you_can_decide, 'the platform lets bob decide').toBe(true)
  const title = forBob.actions[0]?.fields.title ?? ''
  expect(title).toContain('LangGraph')

  const aliceContext = await devContext(browser, 'alice')
  const alice = await aliceContext.newPage()
  const aliceWatch = watchPage(alice)
  await alice.goto(`/runs/${runId}`)
  await expect(state(alice)).toHaveText('Waiting for approval')
  await expect(alice.locator('#decision'), 'opening a waiting run lands on the decision').toBeFocused()
  await expect(alice.getByRole('main')).toContainText(title)
  await expect(alice.getByRole('main')).toContainText('You can’t approve your own run.')
  await expect(alice.getByRole('button', { name: /^(Approve|Decline)/ }), 'no dead button for her own work').toHaveCount(0)
  await shot(alice, info, 'p5-02-alice-own-run')
  assertClean(aliceWatch)
  await aliceContext.close()

  const bobContext = await devContext(browser, 'bob')
  const bob = await bobContext.newPage()
  const bobWatch = watchPage(bob)
  await bob.goto(`/runs/${runId}`)
  await expect(state(bob), 'the status is the same for everyone, in approval words').toHaveText('Waiting for approval')
  await expect(heading(bob), 'the page is named for the workflow the check belongs to').toHaveText('Software watchlist')
  await expect(bob.locator('#decision')).toBeFocused()
  const main = bob.getByRole('main')
  await expect(main).toContainText('This run wants to create 1 Jira ticket in MOCK:')
  await expect(main, 'the page no longer carries the AI’s summary or Not checked').not.toContainText(/Summary by AI|Not checked/)
  await expect(approvalPill(bob), 'the run page shows one pill, the run’s').toHaveCount(0)
  await expect(bob.locator('#decision').getByText(title, { exact: true }).first(), 'the ticket is a small preview, its title first').toBeVisible()
  await bob.getByText('Show full text', { exact: true }).click()
  await expect(bob.locator('#decision'), 'exactly what will be written, from the request, once the full text is open').toContainText(new RegExp(`Where\\s*Jira project MOCK on the practice Jira\\s*Summary\\s*${escaped(title)}`))
  await expect(bob.locator('#decision'), 'when the Approver was asked, and who decides').toContainText(/An Approver decides in Teams \(asked [^)]+\)\./)
  await showHistory(bob)
  await expect(bob.locator('li[aria-current="step"]')).toContainText('Waits for approval')
  expect(await runLinks(bob), 'amber dashes lead into the yes that waits, and the links into the steps done are solid').toEqual(['solid', 'wait', 'todo'])
  await expect(steps(bob), 'the line is the workflow’s blocks and nothing else').toHaveText([/Started by Alice$/, /Read every source$/, /Ask for approval\s*Sent to .+ in Teams$/, /Create Jira tickets$/])
  await expect(sentLine(bob), 'the gate says who the request went to in Teams, and never Alice, whose run it is').toHaveText(SENT_TO_BOB)
  expect(await faceTick(steps(bob).nth(1)), 'the agent that finished looks done when the page opens').toBe('1')
  await shot(bob, info, 'p5-02-bob-waiting')

  const ticketsBefore = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(ticketsBefore, 'nothing is written before the yes').toEqual([])
  await bob.getByRole('button', APPROVE).click()

  await expect(state(bob)).toHaveText('Done', { timeout: 60_000 })
  await expect(steps(bob)).toHaveCount(4)
  for (const step of await steps(bob).all()) await expect(step).toHaveAttribute('data-state', 'done')
  await expect.poll(() => runLinks(bob), { message: 'every link is solid once the run is done' }).toEqual(['solid', 'solid', 'solid'])
  await expect.poll(() => faceTick(steps(bob).nth(1)), { message: 'and still looks done after the run moved on' }).toBe('1')
  const said = bob.locator('[data-gate-said]').last()
  await expect(said, 'Bob opened Run history, so after his approval focus moves to his row in it').toBeFocused()
  await expect(said).toContainText('Bob approved')
  await expect(said.locator('time'), 'the approval has its time to the second, with its day only if the day changed').toHaveText(/^(\w{3} \d{1,2} \w{3}, )?\d{1,2}:\d{2}:\d{2}$/)

  const written = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(written.map((ticket) => ticket.title)).toEqual([title])
  await expect(stepLog(bob)).toContainText(`Created ${written[0]?.key ?? ''}`)
  const key = written[0]?.key ?? ''
  await expect(steps(bob).last().getByRole('link', { name: key }), 'the ticket pops out under its step and opens it').toHaveAttribute('href', new RegExp(`/${key}$`))
  await expect(bob.locator('#decision'), 'the decision says who approved, and what was created').toContainText(new RegExp(`Approved by Bob (at|on \\w{3} \\d{1,2} \\w{3} at) \\d{1,2}:\\d{2}\\. ${key} created\\.`))
  expect((await backend.run(runId)).state).toBe('succeeded')
  await shot(bob, info, 'p5-02-bob-done')
  assertClean(bobWatch)
  await bobContext.close()
})

test('the link in a Teams message opens the run page at the decision', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const message = (await backend.teamsMessages()).find((item) => item.approval_id === approvalId)
  expect(message?.link).toBe(`/approvals/${approvalId}`)

  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/')
  const teams = page.getByRole('button', { name: /^Teams, practice copy, \d+ (or more )?approvals? waiting for you$/ })
  await expect(teams, 'the Teams button counts what waits for bob').toBeVisible({ timeout: 15_000 })
  await teams.click()
  const drawer = page.getByRole('dialog', { name: 'Teams, practice copy' })
  const card = drawer.locator(`li[data-approval-id="${approvalId}"]`)
  // The card a real Teams channel gets: one link to the approval page at its full address. Bob may decide, so the drawer also gives him Approve and Decline.
  await expect(card.getByRole('link', { name: 'Open in AI Workflow Builder' })).toHaveAttribute('href', new RegExp(`^https?://[^/]+/approvals/${approvalId}$`))
  await expect(card.getByRole('button', { name: /^(Approve|Decline)$/ })).toHaveText(['Approve', 'Decline'])
  await shot(page, info, 'p5-02-teams-drawer')
  await card.getByRole('link', { name: 'Open in AI Workflow Builder' }).click()
  await expect(page).toHaveURL(new RegExp(`/approvals/${approvalId}$`))
  await expect(drawer).toBeHidden()
  await expect(page.locator('#decision')).toBeFocused()
  await expect(page.getByRole('button', APPROVE)).toBeVisible()

  await decline(page)
  await expect(state(page)).toHaveText('Declined', { timeout: 60_000 })
  await expect(page.locator('#decision')).toContainText(/Declined by Bob (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}\./)
  await expect(page.getByRole('main')).toContainText('Nothing was written.')
  expect(await runLinks(page), 'faint dots lead into the write that was not needed').toEqual(['solid', 'solid', 'dead'])
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId)).toEqual([])
  assertClean(watch)
  await context.close()
})

test('the Teams drawer gives the person who started the run no Approve or Decline, and Bob’s Decline there ends the run as on the page', async ({ browser, backend }) => {
  const { runId, approvalId } = await backend.waitingRun('alice')

  const aliceContext = await devContext(browser, 'alice')
  const alice = await aliceContext.newPage()
  await alice.goto('/')
  await alice.getByRole('button', { name: /^Teams, practice copy/ }).click()
  const aliceCard = alice.getByRole('dialog', { name: 'Teams, practice copy' }).locator(`li[data-approval-id="${approvalId}"]`)
  await expect(aliceCard.getByRole('link', { name: 'Open in AI Workflow Builder' })).toBeVisible({ timeout: 15_000 })
  await expect(aliceCard.getByRole('button', { name: /^(Approve|Decline)$/ })).toHaveCount(0)
  await aliceContext.close()

  const bobContext = await devContext(browser, 'bob')
  const bob = await bobContext.newPage()
  await bob.goto('/')
  await bob.getByRole('button', { name: /^Teams, practice copy, \d+ (or more )?approvals? waiting for you$/ }).click()
  const bobCard = bob.getByRole('dialog', { name: 'Teams, practice copy' }).locator(`li[data-approval-id="${approvalId}"]`)
  await bobCard.getByRole('button', { name: 'Decline', exact: true }).click()
  await expect(bobCard).toContainText('You declined this.', { timeout: 30_000 })
  await expect.poll(async () => (await backend.get<{ steps: { status: string }[] }>('bob', `/api/v1/approvals/${approvalId}`)).steps.map((step) => step.status), { timeout: 60_000 }).toEqual(['declined'])
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId)).toEqual([])
  await bobContext.close()
})

for (const phone of [false, true]) {
  const width = phone ? '390' : '1440'

  test(`scenario C at ${width} px: bob sees what was found, the ticket as a preview, who decides and when they were asked, with the history folded below`, async ({ browser, backend }, info) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const answered = await backend.get<{ found: string; owner: string; started_by: string; use_case_name: string }>('bob', `/api/v1/approvals/${approvalId}`)
    expect(answered.found, 'the platform holds the summary while the request waits').not.toBe('')
    const context = await devContext(browser, 'bob', { phone })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(state(page)).toHaveText('Waiting for approval')
    await expect(page.locator('#decision')).toBeFocused()
    await expect(page.locator('#decision'), 'what the run wants to do comes before who decides').toContainText(/This run wants to create 1 Jira ticket in MOCK:[\s\S]*An Approver decides in Teams/)
    await expect(approvalPill(page), 'one pill on the page').toHaveCount(0)
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `run-waiting-bob-${width}`)
    await page.getByText('Show full text', { exact: true }).click()
    await expect(page.locator('#decision')).toContainText(/Where\s*Jira project MOCK on the practice Jira\s*Summary/)
    await expect(page.locator('#decision'), 'when it went to Teams').toContainText(/An Approver decides in Teams \(asked (\d{1,2}:\d{2}|\w{3} \d{1,2} \w{3}, \d{1,2}:\d{2})\)\./)
    await expect(page.getByRole('main'), 'the AI’s summary, Not checked and the old rows are gone from the page').not.toContainText(/Summary by AI|Not checked|Why you|What will be written/)
    await expect(page.getByRole('main')).not.toContainText(answered.found)
    await expect(page.getByRole('main'), 'today’s rule: no stop time or backup is named').not.toContainText(/backup|expires|reminder/i)
    await expect(page.getByRole('button', { name: /^(Approve|Decline)$/ })).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Ask Alice', exact: true })).toBeVisible()

    await expect(page.locator('summary', { hasText: /^Run history \(\d+ steps?\)$/ }), 'the history is folded while a request waits').toBeVisible()
    await showHistory(page)
    await expect(sentLine(page)).toHaveText(SENT_TO_BOB)
    await expect(stepLog(page)).toContainText('Asked an Approver in Teams')
    await expect(stepLog(page), 'the agents’ own words are not among the steps').not.toContainText('Version checker')
    await page.getByRole('button', { name: 'Show agent messages' }).click()
    await expect(agentMessages(page), 'the agents’ own words, for support').toContainText('Version checker')
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await shot(page, info, `n15-c-bob-${width}`)
    assertClean(watch)
    await context.close()
  })

  test(`scenario C-self at ${width} px: alice reads that she cannot approve her own run, with no button`, async ({ browser, backend }, info) => {
    const { runId } = await backend.waitingRun('alice')
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(state(page)).toHaveText('Waiting for approval')
    await expect(page.locator('#decision')).toContainText('An Approver decides in Teams')
    await expect(page.locator('#decision')).toContainText('You can’t approve your own run.')
    await showHistory(page)
    await expect(sentLine(page), 'her request went to the other Approvers, never to her').toHaveText(SENT_TO_BOB)
    await expect(sentLine(page)).not.toContainText('Alice')
    await expect(page.getByRole('button', { name: /^(Approve|Decline)/ }), 'no dead button').toHaveCount(0)
    await expect(approvalPill(page), 'one pill on the page, the run’s').toHaveCount(0)
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `run-waiting-alice-${width}`)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await shot(page, info, `n15-c-self-alice-${width}`)
    assertClean(watch)
    await context.close()
  })
}

test('scenario C: the agents’ words are never a summary on the page, before or after bob decides, and stay under Show agent messages', async ({ browser, backend }) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const found = (await backend.get<{ found: string }>('bob', `/api/v1/approvals/${approvalId}`)).found
  expect(found, 'the platform still holds the agents’ report while the request waits').not.toBe('')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`)
  await expect(page.locator('#decision')).toBeVisible()
  await expect(page.getByRole('main')).not.toContainText('Summary by AI')
  await decline(page)
  await expect(state(page)).toHaveText('Declined', { timeout: 60_000 })
  expect((await backend.get<{ found: string }>('bob', `/api/v1/approvals/${approvalId}`)).found, 'the approval no longer carries it').toBe('')
  await showHistory(page)
  await expect(stepLog(page), 'the plain steps do not repeat the agents’ report').not.toContainText(found.split('.')[0] ?? found)
  await page.getByRole('button', { name: 'Show agent messages' }).click()
  await expect(agentMessages(page), 'a finished run keeps the agents’ own words for support').toContainText('Version checker')
  await context.close()
})

test('the stage plays each hand-off once as a glowing dot, holds the dashes still, and holds still with reduced motion', async ({ browser, backend }, info) => {
  const { runId } = await backend.waitingRun('alice')
  const frames = path.join(OUT, 'shots')
  for (const reducedMotion of [false, true]) {
    const context = await devContext(browser, 'alice', { reducedMotion })
    const page = await context.newPage()
    await holdRunAtWork(page, runId)
    await page.goto(`/runs/${runId}`)
    await expect(state(page)).toHaveText('Running')
    const line = page.getByRole('list', { name: 'Steps of this run' })
    await expect(line.locator('li[aria-current="step"]'), 'the step at work says how long it has worked').toContainText(/Read every source\s*Working, \d+ (s|min|h)$/)
    expect(await runLinks(page), 'the same dashes into the step at work, holding still').toEqual(['flow', 'todo', 'todo'])
    if (reducedMotion) {
      await expect(page.locator('[data-glow]'), 'no glowing dot is drawn').toHaveCount(0)
      expect(await linkAnimations(page), 'no animation runs on the links or the hand-offs').toEqual([])
      await shot(page, info, 'r11-02-at-work-reduced')
      for (const frame of [1, 2]) {
        await line.screenshot({ path: path.join(frames, `r11-march-reduced-${String(frame)}.png`) })
        await page.waitForTimeout(200)
      }
    } else {
      await expect(page.locator('[data-glow]').first(), 'a dot runs along the hand-off into the step at work').toBeAttached()
      await shot(page, info, 'r11-02-at-work')
      for (const frame of [1, 2, 3]) {
        await line.screenshot({ path: path.join(frames, `r11-march-${String(frame)}.png`) })
        await page.waitForTimeout(200)
      }
      await expect.poll(() => linkAnimations(page), { message: 'once the dot has run, nothing animates on the links or the hand-offs', timeout: 10_000 }).toEqual([])
    }
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    await context.close()
  }
})

test('scenario B: a stopped run opens on the three answers, an Operator retries it on the page, and an Approver is told who can', async ({ browser, backend }, info) => {
  let runId = ''
  try {
    await setMockGithubMode('unavailable')
    runId = await backend.startCheck('alice')
    await backend.waitForState(runId, ['failed'], 150_000)
  } finally {
    await setMockGithubMode('ok')
  }
  const stopped = await backend.run(runId)
  expect(stopped.retryable, 'the platform says this stop can be retried').toBe(true)

  const bobContext = await devContext(browser, 'bob')
  const bob = await bobContext.newPage()
  await bob.goto(`/runs/${runId}`)
  await expect(state(bob)).toHaveText('Stopped')
  await expect(bob.getByRole('button', { name: 'Retry', exact: true }), 'an Approver has no Retry').toHaveCount(0)
  for (const name of ['What happened', 'Affected', 'Safe to retry']) await expect(answer(bob, name), `Bob sees ${name}`).toBeVisible()
  await expect(answer(bob, 'Safe to retry')).toContainText('Yes.')
  await expect(bob.getByRole('main')).toContainText('An Operator can retry the run.')
  await bobContext.close()

  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto(`/runs/${runId}`)
  const stop = page.getByRole('list', { name: 'Steps of this run' }).locator('li[data-state="err"]')
  await expect(stop, 'the stage is still at the stop: no glow runs into it').toBeVisible()
  await expect(stop, 'the stop is named in words for a screen reader').toContainText(/Stopped\s*Read every source/)
  await expect(state(page)).toHaveText('Stopped')
  await expect(page.locator('#decision')).toBeFocused()
  for (const name of ['What happened', 'Affected', 'Safe to retry']) await expect(answer(page, name), name).toBeVisible()
  await expect(page.locator('#decision dt'), 'three answers, no fourth').toHaveText(['What happened', 'Affected', 'Safe to retry'])
  await expect(answer(page, 'Safe to retry')).toContainText('Yes. Nothing was written, so a retry is safe.')
  await expect(answer(page, 'Affected')).toContainText('Nothing. No ticket was written.')
  await page.getByText('Details', { exact: true }).click()
  await expect(page.locator('#decision')).toContainText('The failure text:')
  expect(await runLinks(page), 'red dashes lead into the stop, and the links after it are plain').toEqual(['stop', 'todo', 'todo'])
  await expect(page.getByRole('main')).not.toContainText(/write key/i)
  await expect(page.getByRole('button', { name: 'Report to support' }), 'a retryable stop offers Retry, not a report').toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Why it stopped' }).getByRole('button', { name: 'Retry', exact: true }), 'Retry sits under the answers').toBeVisible()
  await shot(page, info, 'n15-b-stopped')

  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect
    .poll(() => runLinks(page), { message: 'mid-run, dashes march into the step at work and the links before it are solid', intervals: [100], timeout: 90_000 })
    .toEqual(['flow+', 'todo', 'todo'])
  await expect(state(page)).toHaveText('Waiting for approval', { timeout: 90_000 })
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'a retry writes nothing before a yes').toEqual([])
  await shot(page, info, 'n15-b-retried')
  assertClean(watch)
  await context.close()
})

test('a Retry that another Operator beat says who retried it, keeps focus on the run, and is read aloud (issue 158)', async ({ browser, backend, baseURL }, info) => {
  await connectMockModel(String(baseURL))
  let runId = ''
  try {
    await setMockGithubMode('unavailable')
    runId = await backend.startCheck('alice')
    await backend.waitForState(runId, ['failed'], 150_000)
  } finally {
    await setMockGithubMode('ok')
  }
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto(`/runs/${runId}`)
  await expect(state(page)).toHaveText('Stopped')
  await page.route(`**/api/v1/runs/${runId}/retry`, async (route) => {
    await backend.post('carol', `/api/v1/runs/${runId}/retry`, undefined, undefined, [202])
    await backend.waitToLeave(runId, 'failed', 60_000)
    await route.continue()
  })
  const answered = page.waitForResponse((response) => response.url().endsWith(`/api/v1/runs/${runId}/retry`), { timeout: 90_000 })
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  expect((await answered).status(), 'Carol retried it first, so the platform refuses Alice’s press').toBe(409)

  const said = 'Carol already retried this run.'
  await expect(page.getByRole('status').filter({ hasText: said }), 'a screen reader hears who retried it').toHaveText(said)
  await expect(page.locator('[aria-hidden="true"]', { hasText: said }), 'and the page shows it').toBeVisible()
  await expect(heading(page), 'focus goes to the run’s name, not the page body').toBeFocused()
  await shot(page, info, 'i158-retried-first')
  await expect(state(page), 'the page shows the run going again').not.toHaveText('Stopped')
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0)
  await expect(page.getByRole('main')).not.toContainText('can’t be retried')
  assertClean(watch)
  await context.close()
})

for (const phone of [false, true]) {
  const width = phone ? '390' : '1440'

  test(`scenario F at ${width} px: a stop that cannot be retried is reported to support once, and the page says where updates appear`, async ({ browser, backend }, info) => {
    let runId = ''
    try {
      await setMockGithubMode('not_found')
      runId = await backend.startCheck('alice')
      await backend.waitForState(runId, ['failed'], 150_000)
    } finally {
      await setMockGithubMode('ok')
    }
    expect((await backend.run(runId)).retryable, 'the platform says this stop cannot be retried').toBe(false)

    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(state(page)).toHaveText('Stopped')
    await expect(page.locator('#decision dt'), 'three answers, no fourth').toHaveText(['What happened', 'Affected', 'Safe to retry'])
    await expect(answer(page, 'Safe to retry')).toContainText(/No\. This kind of stop can't be retried\./)
    await expect(page.getByRole('main')).toContainText('Report it. Support gets the run and this explanation')
    await expect(page.getByRole('button', { name: 'Retry', exact: true }), 'no Retry for a stop that cannot be retried').toHaveCount(0)
    await expect(page.getByRole('main')).not.toContainText(/write key/i)
    await page.getByText('Details', { exact: true }).click()
    await expect(page.locator('#decision')).toContainText('The failure text: Could not check LangGraph')
    await page.getByLabel(/Anything to add/).fill('Seen on the Friday check.')
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await expectAccessible(page, path.join(OUT, 'axe'), `run-stopped-alice-${width}`)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await shot(page, info, `n15-f-before-${width}`)

    await page.getByRole('button', { name: 'Report to support' }).click()
    const sent = page.getByRole('status').filter({ hasText: 'You reported this to support.' })
    await expect(sent).toBeVisible()
    await expect(sent).toContainText('Updates appear under Following up on Workflows.')
    await expect(page.getByRole('button', { name: 'Report to support' }), 'the button is gone once it is sent').toHaveCount(0)

    const made = (await backend.get<{ requests: { request_id: string; kind: string; about: Record<string, string>; note: string; posted_to_teams: boolean; not_posted_because: string | null }[] }>('alice', '/api/v1/team-requests')).requests.filter(
      (request) => request.about['run_id'] === runId,
    )
    expect(made, 'one request for this run').toHaveLength(1)
    expect(made[0]?.kind).toBe('support')
    expect(made[0]?.note).toContain('Note from Alice: Seen on the Friday check.')
    const delivery = made[0]?.posted_to_teams ? 'also posted in the team’s Teams channel' : /No Teams channel is set up|Teams did not take it|still going/
    await expect(sent).toContainText(delivery)
    const link = sent.getByRole('link', { name: 'Open it under Following up' })
    await expect(link).toHaveAttribute('href', `/workflows?request=${made[0]?.request_id}`)

    await showHistory(page)
    await expect(stepLog(page).getByText('Alice reported this run to support.')).toHaveCount(1)
    const events = (await backend.get<{ events: { kind: string }[] }>('alice', `/api/v1/runs/${runId}/events?after=0`)).events
    expect(events.filter((event) => event.kind === 'support_reported'), 'the event is written once').toHaveLength(1)
    await shot(page, info, `n15-f-sent-${width}`)

    await page.reload()
    await expect(state(page)).toHaveText('Stopped')
    await expect(page.getByRole('status').filter({ hasText: 'You reported this to support.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Report to support' }), 'a later visit shows it reported, with no second button').toHaveCount(0)
    const again = (await backend.get<{ requests: { about: Record<string, string> }[] }>('alice', '/api/v1/team-requests')).requests.filter((request) => request.about['run_id'] === runId)
    expect(again).toHaveLength(1)
    assertClean(watch)
    await context.close()
  })
}

const RECORD = 'Declined by Bob. Nothing was written. Reason: Wrong version.'
const pill = (page: Page) => state(page).filter({ hasText: 'Declined' })
const DECLINED_LINE = 'Bob declined: wrong version. Nothing was written.'
const softwareRow = (page: Page, name: string) => page.locator('li[data-status]').filter({ hasText: name })

/** The run page, Workflows and the watchlist give the same declined record, and none of them a write. */
async function expectDeclinedEverywhere(page: Page, runId: string, info: TestInfo, who: string, width: number): Promise<void> {
  await page.goto(`/runs/${runId}`)
  await expect(state(page)).toHaveText('Declined')
  await expect(pill(page), 'the pill says Declined in words').toBeVisible()
  await expect(page.getByRole('main')).toContainText(DECLINED_LINE)
  await shot(page, info, `r12-run-page-${who}-${width}`)
  await page.goto('/workflows')
  const workflow = page.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })
  await expect(workflow.getByText(/Declined by Bob\. Nothing was written\./), 'the Workflows row names who declined, in its Last run').toBeVisible()
  await expect(workflow).not.toContainText(/created|Sent/)
  await workflow.scrollIntoViewIfNeeded()
  await shot(page, info, `r12-workflows-${who}-${width}`)
  await page.goto('/software')
  const row = softwareRow(page, 'LangGraph')
  await expect(row).toContainText('Newer out')
  await row.getByRole('link').click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('LangGraph')
  await expect(page.getByRole('main'), 'the software page gives the record as its Upgrade ticket').toContainText(RECORD)
  await shot(page, info, `r12-watchlist-${who}-${width}`)
}

for (const phone of [false, true]) {
  const width = phone ? 390 : 1280

  test(`APPR-decline at ${width} px: Decline asks why with quick reasons, and the reason shows with the one declined record wherever the run shows`, async ({ browser, backend }, info) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const bobContext = await devContext(browser, 'bob', { phone })
    const bob = await bobContext.newPage()
    if (!phone) await bob.setViewportSize({ width, height: 900 })
    const watch = watchPage(bob)
    await bob.goto(`/runs/${runId}`)
    await bob.getByRole('button', { name: 'Decline' }).click()
    const why = declineReasons(bob)
    await expect(why).toContainText('Why? Optional. Alice will see it.')
    await expect(why.getByRole('button'), 'the quick reasons, then Back, and Decline last').toHaveText(['Not this week', 'Wrong version', 'Needs testing first', 'Back', 'Decline'])
    await expect(why.getByRole('button', { name: 'Not this week' }), 'focus is on the first reason').toBeFocused()
    await expect(state(bob), 'nothing is declined yet').toHaveText('Waiting for approval')
    await why.getByRole('button', { name: 'Wrong version' }).click()
    await expect(why.locator('[aria-pressed="true"]'), 'one reason is picked').toHaveText('Wrong version')
    await expectAccessible(bob, path.join(OUT, 'axe'), `decline-reasons-${width}`)
    await shot(bob, info, `r12-decline-dialog-bob-${width}`)
    await why.getByRole('button', { name: 'Decline' }).click()
    await expect(bob.getByRole('status').filter({ hasText: 'Declined. Nothing was written. Reason: Wrong version.' }), 'a message at the bottom tells Bob, said once').toHaveCount(1)
    await shot(bob, info, `r15-declined-message-bob-${width}`)

    await expect(state(bob)).toHaveText('Declined', { timeout: 60_000 })
    await expect(bob.locator('#decision')).toContainText(/Declined by Bob (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}: wrong version\. Nothing was written\./)
    await expect(pill(bob)).toBeVisible()
    await showHistory(bob)
    await expect(steps(bob).filter({ hasText: 'Nothing written' }), 'the write step says nothing was written').toHaveCount(1)
    const shown = await steps(bob).last().getByText('Nothing written').evaluate((note) => {
      let opacity = 1
      for (let node: Element | null = note; node; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity)
      return opacity
    })
    expect(shown, 'the skipped step fades, but what it says under it keeps full contrast').toBe(1)
    await expect(steps(bob).last(), 'the write is the last step, skipped').toHaveAttribute('data-state', 'skip')
    await expect(steps(bob).nth(2), 'the gate shows the decline').toHaveAttribute('data-state', 'no')
    await expect(stepLog(bob)).toContainText(DECLINED_LINE)
    await expect(stepLog(bob), 'the log never says anything was created').not.toContainText(/Done\.|created/)

    const view = await backend.get<{ steps: { status: string; reason: string | null }[] }>('bob', `/api/v1/approvals/${approvalId}`)
    expect(view.steps.map((step) => [step.status, step.reason])).toEqual([['declined', 'Wrong version']])
    expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing was written').toEqual([])
    if (!phone) {
      await bob.getByRole('button', { name: /^Teams, practice copy/ }).click()
      const card = bob.getByRole('dialog', { name: 'Teams, practice copy' }).locator(`li[data-approval-id="${approvalId}"]`)
      await expect(card, 'Teams gives the same record').toContainText(/Declined by Bob\s*Nothing was written\. Reason: Wrong version\./)
      await bob.keyboard.press('Escape')
    }
    await expectDeclinedEverywhere(bob, runId, info, 'bob', width)
    assertClean(watch)
    await bobContext.close()

    const aliceContext = await devContext(browser, 'alice', { phone })
    const alice = await aliceContext.newPage()
    if (!phone) await alice.setViewportSize({ width, height: 900 })
    await expectDeclinedEverywhere(alice, runId, info, 'alice', width)
    if (!phone) {
      const saved = await backend.saveWatchlistSchedule('alice', { day: 'monday', at: '09:00' })
      expect(saved.status, 'a weekly check is set').toBe(200)
      try {
        // On a Monday before 9:00 the next check is today, and near New Year it carries the year, as runWhen says it.
        const next = /The tickets will be proposed again at the next check, (Today|Mon \d+ \w+( \d{4})?), 9:00\./
        await alice.goto('/software')
        await softwareRow(alice, 'LangGraph').getByRole('link').click()
        await expect(alice.getByRole('main'), 'the software page says when the tickets are proposed again').toContainText(next)
        await shot(alice, info, `r12-watchlist-next-check-alice-${width}`)
        await alice.goto(`/runs/${runId}`)
        await expect(alice.getByRole('main'), 'the run page gives the same next step').toContainText(next)
      } finally {
        await backend.turnOffWatchlistSchedule('alice')
      }
    }
    await aliceContext.close()
  })
}

test('APPR-decline-none: a decline needs no reason, and then the record gives none', async ({ browser, backend }) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`)
  await decline(page)
  await expect(state(page)).toHaveText('Declined', { timeout: 60_000 })
  await expect(page.locator('#decision')).toContainText(/Declined by Bob (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}\. Nothing was written\./)
  await expect(page.getByRole('main')).not.toContainText('Reason:')
  const view = await backend.get<{ steps: { reason: string | null }[] }>('bob', `/api/v1/approvals/${approvalId}`)
  expect(view.steps.map((step) => step.reason)).toEqual([null])
  await context.close()
})

test('APPR-decide-nav: a half-picked decline reason does not survive leaving the page', async ({ browser, backend }) => {
  const { runId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`)
  await page.getByRole('button', { name: 'Decline' }).click()
  await declineReasons(page).getByRole('button', { name: 'Wrong version' }).click()
  await page.getByRole('navigation', { name: 'Browse' }).getByRole('link', { name: /^Workflows/ }).click()
  await expect(heading(page), 'the run page is left').toHaveText('Workflows')
  await page.goBack()
  await expect(state(page)).toHaveText('Waiting for approval')
  await expect(declineReasons(page), 'the reasons are closed').toHaveCount(0)
  await expect(page.getByRole('button', { name: /^(Approve|Decline)$/ }), 'Approve and Decline are back').toHaveCount(2)
  expect((await backend.run(runId)).state, 'nothing was decided').toBe('awaiting_approval')
  await context.close()
})

const WIDTHS = [1920, 1280, 900, 390] as const
const questionsOf = (page: Page) => page.getByRole('region', { name: 'Questions' })
const sentToast = (page: Page) => page.getByRole('status').filter({ hasText: /^Sent to / })
const escaped = (words: string) => words.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
/** Lines of the thread in order, whatever space the page puts between them. */
const inOrder = (...lines: string[]) => new RegExp(lines.map(escaped).join('\\s*'))
/** Puts focus before the first control, as a fresh page has it, the way the prototype's scenario starts. */
const focusTop = (page: Page) =>
  page.evaluate(() => {
    const probe = document.createElement('span')
    probe.tabIndex = -1
    document.body.prepend(probe)
    probe.focus()
    probe.remove()
  })
const ringShows = (page: Page) =>
  page.evaluate(() => {
    const el = document.activeElement
    if (!el) return false
    const style = getComputedStyle(el)
    return (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0) || style.boxShadow !== 'none'
  })

async function opened(browser: Browser, user: string, width: number): Promise<{ context: BrowserContext; page: Page }> {
  const context = await devContext(browser, user, { phone: width === 390 })
  const page = await context.newPage()
  if (width !== 390) await page.setViewportSize({ width, height: 900 })
  return { context, page }
}

async function asked(backend: Backend, approvalId: string, text: string, key: string): Promise<string> {
  const question = await backend.post<{ question_id: string }>('bob', `/api/v1/approvals/${approvalId}/questions`, { text }, { 'Idempotency-Key': key })
  return question.question_id
}

for (const width of WIDTHS) {
  test(`APPR-ask at ${width} px: bob asks alice a question, the request keeps waiting, and her answer shows under it`, async ({ browser, backend }, info) => {
    const question = 'Has the 1.2.16 change been tested with our login service?'
    const { runId, approvalId } = await backend.waitingRun('alice')
    const { context, page: bob } = await opened(browser, 'bob', width)
    const watch = watchPage(bob)
    await bob.goto(`/runs/${runId}`)
    await bob.getByRole('button', { name: 'Ask Alice', exact: true }).click()
    const box = bob.getByRole('textbox', { name: 'Ask Alice a question' })
    await expect(box, 'focus is in the question box').toBeFocused()
    await expect(bob.getByRole('button', { name: 'Back', exact: true }), 'Back closes the box').toBeVisible()
    await bob.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(bob.getByRole('main'), 'an empty question is asked for').toContainText('Type your question.')
    await expect(box).toBeFocused()
    await box.fill(question)
    await expectAccessible(bob, path.join(OUT, 'axe'), `ask-box-${width}`)
    await shot(bob, info, `r13-ask-box-bob-${width}`)
    await bob.getByRole('button', { name: 'Send', exact: true }).click()

    const thread = questionsOf(bob)
    await expect(thread).toContainText(inOrder(`You asked Alice: ${question}`, 'No reply yet. The request stays open.'))
    await expect(thread.getByRole('heading', { name: 'Questions' }), 'focus is on the questions’ heading').toBeFocused()
    await expect(sentToast(bob), 'a toast says it was sent').toHaveText('Sent to Alice. The request is still waiting for approval.')
    await expect(thread.getByRole('heading', { name: 'Questions' }), 'the toast leaves focus where it was').toBeFocused()
    await expect(state(bob), 'the request still waits for approval').toHaveText('Waiting for approval')
    await expect(bob.getByRole('button', { name: /^(Approve|Decline)$/ }), 'Approve and Decline are still there').toHaveCount(2)
    expect((await backend.run(runId)).state, 'nothing was decided').toBe('awaiting_approval')

    const view = await backend.get<{ questions: { question_id: string }[] }>('bob', `/api/v1/approvals/${approvalId}`)
    const [sent] = view.questions
    await backend.post('alice', `/api/v1/approvals/${approvalId}/questions/${sent?.question_id ?? ''}/answer`, { text: 'Yes. I checked it with the team on Friday.' })
    await expect(thread, 'alice’s answer shows under it').toContainText(inOrder(question, 'Alice answered: Yes. I checked it with the team on Friday.'), { timeout: 15_000 })
    await expect(state(bob), 'it still waits for approval').toHaveText('Waiting for approval')
    await expect(bob.getByRole('button', APPROVE), 'bob still decides').toHaveCount(1)
    await thread.scrollIntoViewIfNeeded()
    await shot(bob, info, `r13-thread-answered-bob-${width}`)
    assertClean(watch)
    await context.close()
  })

  test(`APPR-answer at ${width} px: alice finds bob’s question in Needs you, answers it on the request, and it still waits for someone else’s yes`, async ({ browser, backend }, info) => {
    const question = 'Should 1.2.16 be in this check?'
    const { runId, approvalId } = await backend.waitingRun('alice')
    const questionId = await asked(backend, approvalId, question, `appr-answer-${width}`)
    const { context, page: alice } = await opened(browser, 'alice', width)
    const watch = watchPage(alice)

    await alice.goto('/')
    const onHome = alice.locator(`li[data-home-item="question:${questionId}"]`)
    await expect(onHome, 'Home’s row names who asked; the question itself is on the request').toContainText(/Bob asked you about /)
    await onHome.scrollIntoViewIfNeeded()
    await shot(alice, info, `r13-needs-you-home-alice-${width}`)

    await alice.goto('/workflows')
    const item = alice.locator(`li[data-home-item="question:${questionId}"]`)
    await expect(item, 'Workflows says the row in Home’s words, as one plain row').toHaveText(/^Bob\s+asked you about Software watchlist$/)
    await item.scrollIntoViewIfNeeded()
    await shot(alice, info, `r13-needs-you-alice-${width}`)
    await item.getByRole('link').click()
    await expect(alice).toHaveURL(new RegExp(`/runs/${runId}$`))
    await expect(questionsOf(alice), 'the request shows the question').toContainText(`Bob asked you: ${question}`)

    const box = alice.getByRole('textbox', { name: 'Your answer for Bob' })
    await expect(box).toBeVisible()
    await expect(alice.getByRole('main')).toContainText('It shows on this request. It doesn’t decide anything.')
    await alice.getByRole('button', { name: 'Send answer' }).click()
    await expect(alice.getByRole('main'), 'an empty answer is asked for').toContainText('Type your answer.')
    await box.fill('Yes, it was released on Friday.')
    await box.scrollIntoViewIfNeeded()
    await expectAccessible(alice, path.join(OUT, 'axe'), `answer-box-${width}`)
    await shot(alice, info, `r13-answer-box-alice-${width}`)
    await alice.getByRole('button', { name: 'Send answer' }).click()

    const thread = questionsOf(alice)
    await expect(thread).toContainText(inOrder(`Bob asked you: ${question}`, 'You answered: Yes, it was released on Friday.'))
    await expect(thread.getByRole('heading', { name: 'Questions' }), 'focus is on the questions’ heading').toBeFocused()
    await expect(sentToast(alice), 'a toast says it was sent').toHaveText('Sent to Bob. The request is still waiting for approval.')
    await expect(alice.getByRole('button', { name: /^Approve/ }), 'alice still can’t approve her own run').toHaveCount(0)
    expect((await backend.run(runId)).state, 'the answer decided nothing').toBe('awaiting_approval')
    await shot(alice, info, `r13-thread-answered-alice-${width}`)
    await alice.goto('/workflows')
    await expect(alice.locator(`li[data-home-item="question:${questionId}"]`), 'the question leaves Needs you').toHaveCount(0)
    assertClean(watch)
    await context.close()
  })

  test(`APPR-thread-kept at ${width} px: once the request is decided its questions stay on the record, read only, for bob and alice`, async ({ browser, backend }, info) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const questionId = await asked(backend, approvalId, 'Is this urgent?', `appr-kept-${width}`)
    const { context, page: bob } = await opened(browser, 'bob', width)
    await bob.goto(`/runs/${runId}`)
    await expect(questionsOf(bob)).toContainText(inOrder('You asked Alice: Is this urgent?', 'No reply yet.'))
    await decline(bob)
    await expect(state(bob)).toHaveText('Declined', { timeout: 60_000 })
    const kept = inOrder('Is this urgent?', 'Not answered before the request was decided.')
    await expect(questionsOf(bob), 'the question is on the record').toContainText(kept)
    await expect(bob.getByRole('button', { name: 'Ask Alice', exact: true }), 'no way to ask').toHaveCount(0)
    await expect(bob.getByRole('textbox'), 'no question or answer box').toHaveCount(0)
    await questionsOf(bob).scrollIntoViewIfNeeded()
    await shot(bob, info, `r13-decided-thread-bob-${width}`)
    await context.close()

    const { context: aliceContext, page: alice } = await opened(browser, 'alice', width)
    await alice.goto(`/runs/${runId}`)
    await expect(state(alice)).toHaveText('Declined')
    await expect(questionsOf(alice)).toContainText(inOrder('Bob asked you: Is this urgent?', 'Not answered before the request was decided.'))
    await expect(alice.getByRole('textbox', { name: 'Your answer for Bob' }), 'alice has no answer box once it is decided').toHaveCount(0)
    await questionsOf(alice).scrollIntoViewIfNeeded()
    await shot(alice, info, `r13-decided-thread-alice-${width}`)
    const late = await backend.send('POST', 'alice', `/api/v1/approvals/${approvalId}/questions/${questionId}/answer`, { text: 'No.' })
    expect(late.status, 'the platform takes no answer after the decision').toBe(409)
    await aliceContext.close()
  })
}

test('KEYS-APPR: Ask, the decline reasons and Decline with the keyboard only, each with a visible focus', async ({ browser, backend }) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const { context, page } = await opened(browser, 'bob', 1280)
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  await focusTop(page)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Skip to main content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(heading(page), 'Skip to main content lands on the heading').toBeFocused()
  const review = page.locator(`li[data-home-item="approval:${approvalId}"]`).getByRole('link')
  await tabTo(page, review, 40)
  expect(await ringShows(page), 'the request’s row on Home has a visible focus').toBe(true)
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
  await expect(state(page)).toHaveText('Waiting for approval')
  await tabTo(page, page.getByRole('button', { name: 'Ask Alice', exact: true }))
  expect(await ringShows(page), 'Ask has a visible focus').toBe(true)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('textbox', { name: 'Ask Alice a question' }), 'focus is in the box').toBeFocused()
  await page.keyboard.type('Is the LangGraph upgrade urgent?')
  await tabTo(page, page.getByRole('button', { name: 'Send', exact: true }), 5)
  expect(await ringShows(page), 'Send has a visible focus').toBe(true)
  await page.keyboard.press('Enter')
  await expect(questionsOf(page)).toContainText('You asked Alice: Is the LangGraph upgrade urgent?')
  await tabTo(page, page.getByRole('button', { name: 'Decline' }), 20)
  await page.keyboard.press('Enter')
  const why = declineReasons(page)
  await expect(why.getByRole('button', { name: 'Not this week' }), 'focus is on the first reason').toBeFocused()
  expect(await ringShows(page), 'the first reason has a visible focus').toBe(true)
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(why.getByRole('button', { name: 'Wrong version' }), 'the pick keeps focus').toBeFocused()
  await expect(why.locator('[aria-pressed="true"]')).toHaveText('Wrong version')
  await tabTo(page, why.getByRole('button', { name: 'Decline' }), 5)
  expect(await ringShows(page), 'Decline has a visible focus').toBe(true)
  await page.keyboard.press('Enter')
  await expect(state(page)).toHaveText('Declined', { timeout: 60_000 })
  await expect(page.getByRole('main')).toContainText('Bob declined: wrong version. Nothing was written.')
  await context.close()
})

/**
 * Not checked (spec 10.4, ADR 0043): what the run couldn't check, from the run and the capability registry, after What will
 * change on the page and in the side panel. Matches APPR-not-checked, APPR-not-checked-jira, C and KEYS-C in checks/paths-v4.cjs.
 */
test.describe('what a run didn’t check', () => {
  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  /**
   * What these tests leave behind: requests that wait, and Carol's workflows. Bob declines the requests, Carol deletes her
   * workflows and the watchlist goes back to LangGraph, so later tests find Needs you as it was. A cleanup that fails is
   * logged, never thrown over the test's own result. There is no route that deletes an agent card, so the cards stay.
   */
  const leftWaiting: string[] = []
  const carolsWorkflows: string[] = []
  test.afterAll(async ({ backend }) => {
    const tidy = async (what: string, step: () => Promise<unknown>) => {
      try {
        await step()
      } catch (error) {
        console.warn(`cleanup: ${what} failed: ${String(error)}`)
      }
    }
    for (const approvalId of leftWaiting.splice(0)) {
      await tidy(`declining ${approvalId}`, async () => {
        const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
        await backend.send('POST', 'bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'decline', digest })
      })
    }
    for (const useCaseId of carolsWorkflows.splice(0)) await tidy(`deleting ${useCaseId}`, () => backend.send('DELETE', 'carol', `/api/v1/use-cases/${useCaseId}`))
    await tidy('resetting the watchlist', () => backend.freshWatchlist('alice'))
  })

  /** The Not checked section, named by its heading. */
  const unchecked = (scope: Page | Locator) => part(scope, 'Not checked')
  const box = (page: Page) => page.getByLabel('Ask, or describe a task')
  const newest = (page: Page) => page.getByRole('list', { name: 'Conversation with the Planner' }).locator(':scope > li').last()
  const sidePanel = (page: Page) => page.locator('#side-panel')
  const noSidewaysScroll = async (page: Page) => {
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
  }

  /** A Jira summary agent like the one the Planner drafts for "sum up the tickets we finished": it reads Jira and proposes one ticket. */
  async function summaryWaiting(backend: Backend, user: string): Promise<WaitingRun> {
    const tag = randomUUID().slice(0, 6)
    const card = await backend.post<{ card_id: string }>(
      user,
      '/api/v1/agent-cards',
      {
        name: `Finished tickets summary ${tag}`,
        purpose: 'Looks at the tickets finished in one Jira project and proposes a summary ticket.',
        good_for: ['Summarise what we finished this week'],
        inputs: [{ name: 'Jira project', kind: 'jira_project', what: 'The project to summarise, and where the summary goes.', example: 'MOCK' }],
        blocks: [
          { say: 'Find the tickets finished since last Friday.', tool: 'jira.search' },
          { say: 'Propose one ticket that lists them.', tool: 'jira.create_ticket' },
        ],
        approvals: [{ tool: 'jira.create_ticket', approvers: 1 }],
      },
      undefined,
      [201],
    )
    const made = await backend.post<{ use_case_id: string }>(
      user,
      '/api/v1/agent-use-cases',
      { name: `Weekly summary ${tag}`, instruction: 'Every Friday, sum up the tickets we closed this week in MOCK.', agents: [{ card_id: card.card_id, values: { 'Jira project': 'MOCK' } }] },
      undefined,
      [201],
    )
    if (user === 'carol') carolsWorkflows.push(made.use_case_id)
    const runId = await backend.checkNow(user, made.use_case_id)
    await backend.waitForState(runId, ['awaiting_approval'])
    const approvalId = await backend.approvalIdOf(runId)
    leftWaiting.push(approvalId)
    return { runId, approvalId }
  }

  /** A Version checker run Carol set up and started, so Alice may decide it in the side panel. */
  async function carolsCheck(backend: Backend): Promise<WaitingRun> {
    const agents = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }]
    const made = await backend.post<{ use_case_id: string }>('carol', '/api/v1/agent-use-cases', { name: `Carol’s check ${randomUUID().slice(0, 6)}`, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents }, undefined, [201])
    carolsWorkflows.push(made.use_case_id)
    const runId = await backend.checkNow('carol', made.use_case_id)
    await backend.waitForState(runId, ['awaiting_approval'])
    const approvalId = await backend.approvalIdOf(runId)
    leftWaiting.push(approvalId)
    return { runId, approvalId }
  }

  test('APPR-not-checked: the run page leaves out what the run didn’t check, for a check that couldn’t read Redis, for bob and alice', async ({ browser, backend }, info) => {
    test.slow()
    const { runId, approvalId } = await backend.waitingRunWithUnread('alice')
    leftWaiting.push(approvalId)
    const forBob = await backend.get<{ not_checked: string[]; actions: { fields: { title: string } }[] }>('bob', `/api/v1/approvals/${approvalId}`)
    expect(forBob.not_checked, 'the run still names the software it couldn’t read').toEqual(['Redis'])
    expect(forBob.actions.map((action) => action.fields.title), 'and proposes no ticket for it').toEqual(['Upgrade LangGraph from 1.2.14 to 1.2.16'])
    for (const user of ['bob', 'alice'] as const) {
      for (const width of WIDTHS) {
        const { context, page } = await opened(browser, user, width)
        const watch = watchPage(page)
        await page.goto(`/runs/${runId}`)
        await expect(state(page)).toHaveText('Waiting for approval')
        await expect(page.locator('#decision')).toContainText('This run wants to create 1 Jira ticket in MOCK:')
        await expect(unchecked(page), 'Not checked is not on the run page').toHaveCount(0)
        await expect(page.getByRole('main')).not.toContainText(/Not checked|Summary by AI/)
        await expect(page.getByRole('button', { name: /^(Approve|Decline)/ }), user === 'bob' ? 'bob decides' : 'alice, whose run it is, has no button').toHaveCount(user === 'bob' ? 2 : 0)
        await noSidewaysScroll(page)
        if (width === 1280) await expectAccessible(page, path.join(OUT, 'axe'), `r14-not-checked-${user}-1280`)
        await shot(page, info, `r14-not-checked-software-page-${user}-${String(width)}`)
        assertClean(watch)
        await context.close()
      }
    }
  })

  test('APPR-not-checked-jira: a ticket summary’s run page asks for approval in the same shape, with no Not checked, for bob and alice', async ({ browser, backend }, info) => {
    test.slow()
    const { runId, approvalId } = await summaryWaiting(backend, 'carol')
    expect((await backend.get<{ not_checked: string[] }>('bob', `/api/v1/approvals/${approvalId}`)).not_checked, 'a workflow of agents names no software').toEqual([])
    for (const user of ['bob', 'alice'] as const) {
      for (const width of WIDTHS) {
        const { context, page } = await opened(browser, user, width)
        const watch = watchPage(page)
        await page.goto(`/runs/${runId}`)
        await expect(state(page)).toHaveText('Waiting for approval')
        await expect(page.locator('#decision')).toContainText('This run wants to create 1 Jira ticket in MOCK:')
        await expect(unchecked(page)).toHaveCount(0)
        await expect(page.getByRole('button', { name: /^(Approve|Decline)/ }), 'carol started it, so both may decide').toHaveCount(2)
        await noSidewaysScroll(page)
        await shot(page, info, `r14-not-checked-summary-page-${user}-${String(width)}`)
        assertClean(watch)
        await context.close()
      }
    }
  })

  test('APPR-not-checked in the side panel: a request opened from the chat has the run page’s shape, with no Not checked, for a check and a ticket summary', async ({ browser, backend }, info) => {
    test.slow()
    const runs = [
      { kind: 'software', run: await carolsCheck(backend) },
      { kind: 'summary', run: await summaryWaiting(backend, 'carol') },
    ] as const
    for (const { kind, run } of runs) {
      for (const width of WIDTHS) {
        const { context, page } = await opened(browser, 'alice', width)
        const watch = watchPage(page)
        await page.goto('/')
        await box(page).fill('What needs me?')
        await box(page).press('Enter')
        await expect(newest(page)).toHaveAttribute('data-answer', 'true')
        await newest(page).locator(`[data-opens="approval:${run.runId}"]`).click()
        const panel = sidePanel(page)
        await expect(panel, 'what the run wants to do, then the whole ticket one click away').toContainText(/This run wants to create 1 Jira ticket in MOCK:[\s\S]*Where[\s\S]*Summary/)
        await expect(unchecked(panel), 'Not checked is not in the panel').toHaveCount(0)
        await expect(panel, 'the AI’s summary and Why you are not in the panel').not.toContainText(/Summary by AI|Why you|Not checked/)
        await noSidewaysScroll(page)
        if (width === 1280) await expectAccessible(page, path.join(OUT, 'axe'), `r14-not-checked-panel-${kind}-1280`)
        await shot(page, info, `r14-not-checked-${kind}-panel-alice-${String(width)}`)
        assertClean(watch)
        await context.close()
      }
    }
  })

  test('KEYS-C: bob reviews a check with something not checked and approves it with the keyboard only', async ({ browser, backend }, info) => {
    const { runId, approvalId } = await backend.waitingRunWithUnread('alice')
    const { context, page } = await opened(browser, 'bob', 1280)
    await page.goto('/')
    await expect(heading(page)).toBeVisible()
    await focusTop(page)
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Skip to main content' })).toBeFocused()
    await page.keyboard.press('Enter')
    await tabTo(page, page.locator(`li[data-home-item="approval:${approvalId}"]`).getByRole('link'))
    expect(await ringShows(page), 'the request’s row on Home has a visible focus').toBe(true)
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
    await tabTo(page, page.getByRole('button', APPROVE), 30)
    expect(await ringShows(page), 'Approve has a visible focus').toBe(true)
    await shot(page, info, 'r14-keys-c-approve-focused-1280')
    await page.keyboard.press('Enter')
    await expect(state(page)).toHaveText('Done', { timeout: 60_000 })
    await expect(page.locator('#decision')).toContainText(/Approved by Bob (at|on \w{3} \d{1,2} \w{3} at) \d{1,2}:\d{2}\. MOCK-\d+ created\./)
    await expect(page.locator('#decision'), 'after the approval, focus is on the decision, which says what happened').toBeFocused()
    expect((await backend.get<{ not_checked: string[] }>('alice', `/api/v1/approvals/${approvalId}`)).not_checked).toEqual(['Redis'])
    await shot(page, info, 'r14-keys-c-decided-bob-1280')
    await context.close()
  })
})
