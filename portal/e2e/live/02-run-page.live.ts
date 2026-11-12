import path from 'node:path'
import type { Page, TestInfo } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { holdRunAtWork, linkAnimations, marchReadings, runLinks } from './support/runLine'
import { setMockGithubMode } from './support/stack'
import { expect, test } from './support/test'
import { decline, declineReasons, devContext, OUT, shot } from './support/ui'

interface ApprovalAnswer {
  actions: { fields: { title: string } }[]
  you_can_decide: boolean
  why_not: string | null
}

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
const toggle = (page: Page) => page.locator('summary', { hasText: /what each agent did$/ })
const agentsSaid = (page: Page) => page.getByRole('list', { name: 'What the agents said' })
const answer = (page: Page, name: string) => page.locator('dl', { has: page.locator('dt', { hasText: new RegExp(`^${name}$`) }) })
/** Every animation that ends has ended. The dashes marching into a yes that waits loop, as they should. */
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().every((animation) => animation.effect?.getComputedTiming().iterations === Infinity))
const steps = (page: Page) => page.getByRole('list', { name: 'Steps of this run' }).locator('li[data-state]')

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
  await expect(heading(alice)).toHaveText('1 ticket is waiting for a yes')
  await expect(alice.locator('#decision'), 'opening a waiting run lands on the decision').toBeFocused()
  await expect(alice.getByRole('main')).toContainText(title)
  await expect(alice.getByRole('main')).toContainText('so another Approver must decide. Nobody approves their own work.')
  await expect(alice.getByRole('button', { name: /^(Approve|Decline)/ }), 'no dead button for her own work').toHaveCount(0)
  await shot(alice, info, 'p5-02-alice-own-run')
  assertClean(aliceWatch)
  await aliceContext.close()

  const bobContext = await devContext(browser, 'bob')
  const bob = await bobContext.newPage()
  const bobWatch = watchPage(bob)
  await bob.goto(`/runs/${runId}`)
  await expect(heading(bob)).toHaveText('1 ticket is waiting for a yes')
  await expect(bob.locator('#decision')).toBeFocused()
  const main = bob.getByRole('main')
  await expect(main).toContainText('1 ticket will be created in Jira project MOCK')
  await expect(main).toContainText(title)
  await expect(main).toContainText('This is exactly what will be written, and nothing else.')
  await expect(bob.locator('li[aria-current="step"]')).toContainText('Waiting for a yes')
  expect(await runLinks(bob), 'slow amber dashes march into the yes that waits, and the links into the steps done are solid').toEqual(['solid', 'solid', 'wait+', 'todo', 'todo'])
  await shot(bob, info, 'p5-02-bob-waiting')

  const ticketsBefore = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(ticketsBefore, 'nothing is written before the yes').toEqual([])
  await bob.getByRole('button', { name: 'Approve 1 ticket' }).click()

  await expect(heading(bob)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
  await expect(steps(bob)).toHaveCount(6)
  for (const step of await steps(bob).all()) await expect(step).toHaveAttribute('data-state', 'done')
  await expect(steps(bob).last()).toContainText('Done: Done')
  await expect.poll(() => runLinks(bob), { message: 'every link is solid once the run is done' }).toEqual(['solid', 'solid', 'solid', 'solid', 'solid'])
  await expect(heading(bob), 'the agents’ chat stays folded, so after the yes focus moves to the heading').toBeFocused()
  await expect(toggle(bob)).toHaveText('Show what each agent did')
  await toggle(bob).click()
  const said = bob.locator('[data-gate-said]').last()
  await expect(said).toContainText('Bob approved.')
  await expect(said.locator('time'), 'the yes has its time in the log, with its day only if the day changed').toHaveText(/^(\w{3} \d{1,2} \w{3}, )?\d{1,2}:\d{2}$/)
  await expect(agentsSaid(bob).locator('time').first(), 'the first entry in the log says its day').toHaveText(/^\w{3} \d{1,2} \w{3}, \d{1,2}:\d{2}$/)

  const written = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(written.map((ticket) => ticket.title)).toEqual([title])
  await expect(main).toContainText(`Created ${written[0]?.key ?? ''} in Jira.`)
  await expect(main).toContainText('Bob approved, and the platform created the ticket.')
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
  // The card a real Teams channel gets: one link to the approval page at its full address, and no Approve or Decline.
  await expect(card.getByRole('link', { name: 'Open in AI Workflow Builder' })).toHaveAttribute('href', new RegExp(`^https?://[^/]+/approvals/${approvalId}$`))
  await expect(card.getByRole('button', { name: /^(Approve|Decline)/ })).toHaveCount(0)
  await shot(page, info, 'p5-02-teams-drawer')
  await card.getByRole('link', { name: 'Open in AI Workflow Builder' }).click()
  await expect(page).toHaveURL(new RegExp(`/approvals/${approvalId}$`))
  await expect(drawer).toBeHidden()
  await expect(page.locator('#decision')).toBeFocused()
  await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()

  await decline(page)
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  await expect(page.getByRole('main')).toContainText('Declined by Bob. Nothing was written.')
  expect(await runLinks(page), 'faint dots lead into the write that was not needed').toEqual(['solid', 'solid', 'solid', 'dead', 'solid'])
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId)).toEqual([])
  assertClean(watch)
  await context.close()
})

for (const phone of [false, true]) {
  const width = phone ? '390' : '1440'

  test(`scenario C at ${width} px: bob sees what changes, why, who asked and his part, with the agents folded`, async ({ browser, backend }, info) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const answered = await backend.get<{ found: string; owner: string; started_by: string; use_case_name: string }>('bob', `/api/v1/approvals/${approvalId}`)
    expect(answered.found, 'the platform holds the summary while the request waits').not.toBe('')
    const context = await devContext(browser, 'bob', { phone })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(heading(page)).toHaveText('1 ticket is waiting for a yes')
    await expect(page.locator('#decision')).toBeFocused()
    for (const name of ['What will change', 'Why', 'Who asked', 'What happens', 'Your part']) await expect(answer(page, name), name).toBeVisible()
    await expect(answer(page, 'Why')).toContainText(answered.found)
    await expect(answer(page, 'Why')).toContainText('What will be written is listed above.')
    await expect(answer(page, 'Who asked')).toContainText(`${answered.use_case_name}, set up by Alice. Alice started this run.`)
    await expect(answer(page, 'What happens')).toContainText('Nothing is written until you say yes.')
    await expect(answer(page, 'What happens')).toContainText('The request waits until someone decides.')
    await expect(answer(page, 'Your part')).toContainText('You can decide because you didn’t set this up or start this run.')
    await expect(page.getByRole('main'), 'today’s rule: no stop time or backup is named').not.toContainText(/backup|expires|reminder/i)
    await expect(page.getByRole('button', { name: /^(Approve|Decline)/ })).toHaveCount(2)

    await expect(toggle(page)).toHaveText('Show what each agent did')
    await expect(agentsSaid(page), 'folded while the run waits for a yes').toBeHidden()
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `run-waiting-bob-${width}`)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await shot(page, info, `n15-c-bob-folded-${width}`)

    await toggle(page).click()
    await expect(toggle(page)).toHaveText('Hide what each agent did')
    await expect(agentsSaid(page)).toBeVisible()
    await expect(agentsSaid(page)).toContainText('Version checker')
    await shot(page, info, `n15-c-bob-open-${width}`)
    await page.reload()
    await expect(heading(page)).toHaveText('1 ticket is waiting for a yes')
    await expect(toggle(page), 'a new visit follows the run again').toHaveText('Show what each agent did')
    assertClean(watch)
    await context.close()
  })

  test(`scenario C-self at ${width} px: alice sees why she cannot decide, with no button`, async ({ browser, backend }, info) => {
    const { runId } = await backend.waitingRun('alice')
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(heading(page)).toHaveText('1 ticket is waiting for a yes')
    const part = answer(page, 'Your part')
    await expect(part).toContainText('You set this workflow up and started this run, so another Approver must decide. Nobody approves their own work.')
    await expect(page.getByRole('button', { name: /^(Approve|Decline)/ }), 'no dead button').toHaveCount(0)
    await expect(answer(page, 'What happens')).toContainText('Nothing is written until an Approver says yes.')
    await expect(answer(page, 'Why')).toBeVisible()
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `run-waiting-alice-${width}`)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await shot(page, info, `n15-c-self-alice-${width}`)
    assertClean(watch)
    await context.close()
  })
}

test('scenario C: once bob has decided, the panel and the run keep the agents’ summary from the activity', async ({ browser, backend }) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const found = (await backend.get<{ found: string }>('bob', `/api/v1/approvals/${approvalId}`)).found
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`)
  await expect(answer(page, 'Why')).toContainText(found)
  await decline(page)
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  expect((await backend.get<{ found: string }>('bob', `/api/v1/approvals/${approvalId}`)).found, 'the approval no longer carries it').toBe('')
  await expect(toggle(page), 'deciding does not open the agents’ chat').toHaveText('Show what each agent did')
  await expect(agentsSaid(page), 'a finished run keeps the agents’ chat folded').toBeHidden()
  await context.close()
})

test('scenario C: a bob who pressed Show what each agent did before deciding still has it open after', async ({ browser, backend }) => {
  const { runId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`)
  await expect(toggle(page)).toHaveText('Show what each agent did')
  await toggle(page).click()
  await expect(agentsSaid(page)).toBeVisible()
  await decline(page)
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  await expect(toggle(page)).toHaveText('Hide what each agent did')
  await expect(agentsSaid(page), 'bob’s own press holds after he decides').toBeVisible()
  await context.close()
})

test('the run line marches into the step at work by moving its dashes only, stops while the tab is hidden, and holds still with reduced motion', async ({ browser, backend }, info) => {
  const { runId } = await backend.waitingRun('alice')
  const frames = path.join(OUT, 'shots')
  for (const reducedMotion of [false, true]) {
    const context = await devContext(browser, 'alice', { reducedMotion })
    const page = await context.newPage()
    await holdRunAtWork(page, runId)
    await page.goto(`/runs/${runId}`)
    await expect(heading(page)).toHaveText('The agents are working')
    const line = page.getByRole('list', { name: 'Steps of this run' })
    const [before, after] = await marchReadings(page)
    if (reducedMotion) {
      expect(await runLinks(page), 'the same dashes into the step at work, holding still').toEqual(['solid', 'flow', 'todo', 'todo', 'todo'])
      expect(after, 'the dashes do not move').toBe(before)
      expect(await linkAnimations(page), 'no animation runs on the links').toEqual([])
      await shot(page, info, 'r11-02-at-work-reduced')
      for (const frame of [1, 2]) {
        await line.screenshot({ path: path.join(frames, `r11-march-reduced-${String(frame)}.png`) })
        await page.waitForTimeout(200)
      }
    } else {
      expect(await runLinks(page), 'dashes march into the step at work, and the links into the steps done are solid').toEqual(['solid', 'flow+', 'todo', 'todo', 'todo'])
      expect(after, 'the dashes move').not.toBe(before)
      expect(await linkAnimations(page), 'the march moves the dashes by transform, and nothing else animates on the links').toEqual([['transform']])
      await shot(page, info, 'r11-02-at-work')
      for (const frame of [1, 2, 3]) {
        await line.screenshot({ path: path.join(frames, `r11-march-${String(frame)}.png`) })
        await page.waitForTimeout(200)
      }
      await page.evaluate(() => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
        document.dispatchEvent(new Event('visibilitychange'))
      })
      const paused = await page.locator('[data-link="flow"]').evaluate((link) => getComputedStyle(link, '::before').animationPlayState)
      expect(paused, 'the march stops while the tab is hidden').toBe('paused')
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
  await expect(heading(bob)).toContainText('Stopped at')
  await expect(bob.getByRole('button', { name: 'Retry the run' }), 'an Approver has no Retry').toHaveCount(0)
  for (const name of ['What happened', 'What was affected', 'Safe to retry']) await expect(answer(bob, name), `Bob sees ${name}`).toBeVisible()
  await expect(answer(bob, 'Safe to retry')).toContainText('Yes.')
  await expect(bob.locator('#decision')).toContainText('An Operator can retry the run.')
  await bobContext.close()

  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto(`/runs/${runId}`)
  await expect(heading(page)).toContainText('Stopped at')
  await expect(page.locator('#decision')).toBeFocused()
  for (const name of ['What happened', 'What was affected', 'Safe to retry']) await expect(answer(page, name), name).toBeVisible()
  await expect(page.locator('#decision dt'), 'three answers, no fourth').toHaveText(['What happened', 'What was affected', 'Safe to retry'])
  await expect(answer(page, 'Safe to retry')).toContainText('Yes. A retry runs the work again, and any write still waits for a yes.')
  await expect(answer(page, 'What was affected')).toContainText('Nothing was written.')
  await expect(answer(page, 'What happened')).toContainText('The failure text:')
  expect(await runLinks(page), 'red dashes lead into the stop, and the links after it are plain').toEqual(['solid', 'stop', 'todo', 'todo', 'todo'])
  await expect(page.getByRole('main')).not.toContainText(/write key/i)
  await expect(toggle(page)).toHaveText('Show what each agent did')
  await expect(page.getByRole('button', { name: 'Report to support' }), 'a retryable stop offers Retry, not a report').toHaveCount(0)
  await shot(page, info, 'n15-b-stopped')

  await page.getByRole('button', { name: 'Retry the run' }).click()
  await expect
    .poll(() => runLinks(page), { message: 'mid-run, dashes march into the step at work and the links before it are solid', intervals: [100], timeout: 90_000 })
    .toEqual(['solid', 'flow+', 'todo', 'todo', 'todo'])
  await expect(heading(page)).toHaveText('1 ticket is waiting for a yes', { timeout: 90_000 })
  await expect(page.getByRole('button', { name: 'Retry the run' })).toHaveCount(0)
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'a retry writes nothing before a yes').toEqual([])
  await shot(page, info, 'n15-b-retried')
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
    await expect(heading(page)).toContainText('Stopped at')
    await expect(page.locator('#decision dt'), 'three answers, no fourth').toHaveText(['What happened', 'What was affected', 'Safe to retry'])
    await expect(answer(page, 'Safe to retry')).toContainText(/No\. This kind of stop can't be retried\./)
    await expect(page.locator('#decision')).toContainText('Report it. Support gets the run and this explanation')
    await expect(page.getByRole('button', { name: 'Retry the run' }), 'no Retry for a stop that cannot be retried').toHaveCount(0)
    await expect(page.getByRole('main')).not.toContainText(/write key/i)
    await expect(answer(page, 'What happened')).toContainText('The failure text: Could not check LangGraph')
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

    await toggle(page).click()
    await expect(agentsSaid(page).getByText('Alice reported this run to support.')).toHaveCount(1)
    const events = (await backend.get<{ events: { kind: string }[] }>('alice', `/api/v1/runs/${runId}/events?after=0`)).events
    expect(events.filter((event) => event.kind === 'support_reported'), 'the event is written once').toHaveLength(1)
    await shot(page, info, `n15-f-sent-${width}`)

    await page.reload()
    await expect(heading(page)).toContainText('Stopped at')
    await expect(page.getByRole('status').filter({ hasText: 'You reported this to support.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Report to support' }), 'a later visit shows it reported, with no second button').toHaveCount(0)
    const again = (await backend.get<{ requests: { about: Record<string, string> }[] }>('alice', '/api/v1/team-requests')).requests.filter((request) => request.about['run_id'] === runId)
    expect(again).toHaveLength(1)
    assertClean(watch)
    await context.close()
  })
}

const RECORD = 'Declined by Bob. Nothing was written. Reason: Wrong version.'
const pill = (page: Page) => heading(page).locator('xpath=..').getByText('Declined', { exact: true })
const softwareRow = (page: Page, name: string) => page.locator('li[data-status]').filter({ hasText: name })

/** The run page, Workflows and the watchlist give the same declined record, and none of them a write. */
async function expectDeclinedEverywhere(page: Page, runId: string, info: TestInfo, who: string, width: number): Promise<void> {
  await page.goto(`/runs/${runId}`)
  await expect(heading(page)).toHaveText('Declined, nothing was written')
  await expect(pill(page), 'the pill says Declined in words').toBeVisible()
  await expect(page.getByRole('main')).toContainText(RECORD)
  await shot(page, info, `r12-run-page-${who}-${width}`)
  await page.goto('/workflows')
  const workflow = page.locator('li[data-workflow-id]').filter({ has: page.getByRole('heading', { name: 'Software watchlist', exact: true }) })
  await expect(workflow.getByText(/^Last run .+ · Declined by Bob$/), 'the Workflows row names who declined, the record’s short form for its one line').toBeVisible()
  await expect(workflow).not.toContainText(/created|Sent/)
  await workflow.scrollIntoViewIfNeeded()
  await shot(page, info, `r12-workflows-${who}-${width}`)
  await page.goto('/software')
  const row = softwareRow(page, 'LangGraph')
  await expect(row).toContainText('New version')
  await expect(row).toContainText(RECORD)
  await row.scrollIntoViewIfNeeded()
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
    await expect(why).toContainText('Why are you declining? Optional. Alice sees it with the record.')
    await expect(why.getByRole('button'), 'the quick reasons, then Decline and Back').toHaveText(['Not this week', 'Wrong version', 'Needs testing first', 'Decline', 'Back'])
    await expect(why.getByRole('button', { name: 'Not this week' }), 'focus is on the first reason').toBeFocused()
    await expect(heading(bob), 'nothing is declined yet').toHaveText('1 ticket is waiting for a yes')
    await why.getByRole('button', { name: 'Wrong version' }).click()
    await expect(why.locator('[aria-pressed="true"]'), 'one reason is picked').toHaveText('Wrong version')
    await expectAccessible(bob, path.join(OUT, 'axe'), `decline-reasons-${width}`)
    await shot(bob, info, `r12-decline-dialog-bob-${width}`)
    await why.getByRole('button', { name: 'Decline' }).click()

    await expect(heading(bob)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
    await expect(bob.getByRole('main')).toContainText(RECORD)
    await expect(pill(bob)).toBeVisible()
    await expect(steps(bob).filter({ hasText: 'Nothing written' }), 'the write step says nothing was written').toHaveCount(1)
    await expect(steps(bob).last(), 'the last step is a plain Ended').toContainText('Ended')
    await expect(steps(bob).last().locator('svg'), 'Ended has no tick').toHaveCount(0)
    await toggle(bob).click()
    await expect(agentsSaid(bob)).toContainText(`${RECORD} The run ended.`)
    await expect(agentsSaid(bob), 'the agents never say they created anything').not.toContainText(/Done\.|created/)

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
      const saved = await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
      expect(saved.status, 'a weekly check is set').toBe(200)
      try {
        const next = /The tickets will be proposed again at the next check, Mon \d+ \w+, 9:00\./
        await alice.goto('/software')
        await expect(softwareRow(alice, 'LangGraph'), 'the row says when the tickets are proposed again').toContainText(next)
        await softwareRow(alice, 'LangGraph').scrollIntoViewIfNeeded()
        await shot(alice, info, `r12-watchlist-next-check-alice-${width}`)
        await alice.goto(`/runs/${runId}`)
        await expect(alice.getByRole('main'), 'the run page gives the same next step').toContainText(next)
      } finally {
        await backend.delete('alice', '/api/v1/watchlist/schedule', [200, 404])
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
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  await expect(page.getByRole('main')).toContainText('Declined by Bob. Nothing was written.')
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
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /^Workflows/ }).click()
  await expect(heading(page), 'the run page is left').toHaveText('Workflows')
  await page.goBack()
  await expect(heading(page)).toHaveText('1 ticket is waiting for a yes')
  await expect(declineReasons(page), 'the reasons are closed').toHaveCount(0)
  await expect(page.getByRole('button', { name: /^(Approve 1 ticket|Decline)$/ }), 'Approve and Decline are back').toHaveCount(2)
  expect((await backend.run(runId)).state, 'nothing was decided').toBe('awaiting_approval')
  await context.close()
})
