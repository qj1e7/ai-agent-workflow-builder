import path from 'node:path'
import type { Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { setMockGithubMode } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

interface ApprovalAnswer {
  actions: { fields: { title: string } }[]
  you_can_decide: boolean
  why_not: string | null
}

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
const toggle = (page: Page) => page.locator('summary', { hasText: /what each agent did$/ })
const agentsSaid = (page: Page) => page.getByRole('list', { name: 'What the agents said' })
const answer = (page: Page, name: string) => page.locator('dl', { has: page.locator('dt', { hasText: new RegExp(`^${name}$`) }) })
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
  await shot(bob, info, 'p5-02-bob-waiting')

  const ticketsBefore = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(ticketsBefore, 'nothing is written before the yes').toEqual([])
  await bob.getByRole('button', { name: 'Approve 1 ticket' }).click()

  await expect(heading(bob)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
  await expect(steps(bob)).toHaveCount(6)
  for (const step of await steps(bob).all()) await expect(step).toHaveAttribute('data-state', 'done')
  await expect(steps(bob).last()).toContainText('Done: Done')
  await expect(heading(bob), 'the agents’ chat stays folded, so after the yes focus moves to the heading').toBeFocused()
  await expect(toggle(bob)).toHaveText('Show what each agent did')
  await toggle(bob).click()
  await expect(bob.locator('[data-gate-said]').last()).toHaveText('Bob approved.')

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

  await page.getByRole('button', { name: 'Decline' }).click()
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  await expect(page.getByRole('main')).toContainText('Bob declined, so nothing was written.')
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
    await page.waitForFunction(() => document.getAnimations().length === 0)
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
    await page.waitForFunction(() => document.getAnimations().length === 0)
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
  await page.getByRole('button', { name: 'Decline' }).click()
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
  await page.getByRole('button', { name: 'Decline' }).click()
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  await expect(toggle(page)).toHaveText('Hide what each agent did')
  await expect(agentsSaid(page), 'bob’s own press holds after he decides').toBeVisible()
  await context.close()
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
  await expect(page.getByRole('main')).not.toContainText(/write key/i)
  await expect(toggle(page)).toHaveText('Show what each agent did')
  await expect(page.getByRole('button', { name: 'Report to support' }), 'a retryable stop offers Retry, not a report').toHaveCount(0)
  await shot(page, info, 'n15-b-stopped')

  await page.getByRole('button', { name: 'Retry the run' }).click()
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
