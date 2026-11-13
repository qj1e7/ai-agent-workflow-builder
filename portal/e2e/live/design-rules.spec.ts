import type { Locator, Page } from '@playwright/test'
import { connectMockModel } from './support/settings'
import { SettingsApi } from './support/settings'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, needsOnWorkflows } from './support/ui'
import { askAndWait, editCard, scheduledWorkflow, tag } from './support/edit'

/**
 * The checkable parts of docs/design/ai-native-principles.md, run on each state of a screen. A failure names the principle it broke.
 * Every later screen change adds its states here.
 */

interface Capability {
  id: string
  plain: string
  state: 'ready' | 'needs_setup' | 'down' | 'planned' | 'unsupported'
}

const main = (page: Page) => page.getByRole('main')
const box = (page: Page) => page.getByLabel('Ask, or describe a task')

async function ask(page: Page, text: string): Promise<void> {
  await box(page).fill(text)
  await box(page).press('Enter')
}

/** Principle 3: one primary action per state. */
async function onePrimary(page: Page, state: string): Promise<void> {
  const primaries = await main(page).locator('[class*="_primary_"]:visible').count()
  expect(primaries, `Principle 3 (one primary action): ${state} shows ${String(primaries)} primary buttons`).toBeLessThanOrEqual(1)
}

/** Principle 5: no claim the system can't back. */
async function noOverclaim(page: Page, state: string): Promise<void> {
  const words = await main(page).innerText()
  expect(words, `Principle 5 (never claim more than the platform can do): ${state} says "Sent"`).not.toMatch(/\bSent to\b|\bWe sent\b/)
  expect(words, `Principle 5: ${state} says "all tickets"`).not.toMatch(/\ball (the )?tickets\b/i)
  expect(words, `Principle 7 (honest states): ${state} says a retired phrase`).not.toMatch(/follow it on Home|Check what I understood/)
}

/** Principle 9: a button that can't work is replaced by its reason. The Send button is the one control that waits for words. */
async function noDeadButtons(page: Page, state: string): Promise<void> {
  const dead = await main(page).locator('button[aria-disabled="true"]:not([aria-label="Send"]), button:disabled:not(textarea)').count()
  expect(dead, `Principle 9 (the person stays in control): ${state} shows ${String(dead)} dead buttons`).toBe(0)
}

/** Principle 4: a clause the Planner didn't follow keeps its cross, and the card never says nothing is unclear while it does. */
async function noPartDropped(page: Page, state: string): Promise<void> {
  const card = main(page).locator('section[data-card]').last()
  await expect(card.locator('[data-mark="no"]'), `Principle 4 (no part dropped): ${state} shows no cross`).not.toHaveCount(0)
  await expect(card, `Principle 4: ${state} says nothing is unclear while a part has a cross`).not.toContainText('Nothing is unclear')
  await expect(card.getByRole('button', { name: 'Set up the part I can' }), `Principle 4: ${state} offers to set up the whole request`).toBeVisible()
}

/** Principle 5: the "I can" lists name only what the platform's registry says is ready. */
async function listsMatchTheRegistry(page: Page, registry: readonly Capability[], state: string): Promise<void> {
  const ready = new Set(registry.filter((entry) => entry.state === 'ready').map((entry) => entry.plain))
  const notReady = new Set(registry.filter((entry) => entry.state !== 'ready').map((entry) => entry.plain))
  const canColumn = main(page).locator('div:has(> h3:text-is("I can")) > ul > li')
  for (const item of await canColumn.allInnerTexts()) {
    expect(ready.has(item.trim()), `Principle 5 (one registry): ${state} lists "${item.trim()}" under I can, but the registry does not say Ready`).toBe(true)
    expect(notReady.has(item.trim()), `Principle 5: ${state} lists a capability that is not Ready`).toBe(false)
  }
}

/** Jira stops answering, so one item sits in Alice's Needs you. The returned function puts it right again. */
async function jiraDown(backend: Backend): Promise<() => Promise<void>> {
  const answering = (on: boolean) => backend.post('alice', '/api/v1/dev/practice-jira/answering', { answering: on })
  await answering(false)
  await backend.post('alice', '/api/v1/settings/connections/jira/check')
  return async () => {
    await answering(true)
    await backend.post('alice', '/api/v1/settings/connections/jira/check')
  }
}

async function allRules(page: Page, registry: readonly Capability[], state: string): Promise<void> {
  await onePrimary(page, state)
  await noOverclaim(page, state)
  await noDeadButtons(page, state)
  if (registry.length > 0) await listsMatchTheRegistry(page, registry, state)
}

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

test('Home keeps the design rules in each of its states', async ({ browser, backend }) => {
  const { capabilities } = await backend.get<{ capabilities: Capability[] }>('alice', '/api/v1/capabilities')
  await backend.waitingRun('alice')
  const repair = await jiraDown(backend)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  await expect(box(page)).toBeVisible()
  await allRules(page, capabilities, 'Alice’s Home')

  await ask(page, 'What can you do?')
  await expect(main(page).getByRole('heading', { name: 'What I can do' })).toBeVisible()
  await allRules(page, capabilities, 'the abilities answer')

  await ask(page, 'Check my workflows')
  await expect(main(page).getByRole('list', { name: 'Your workflows' })).toBeVisible()
  await allRules(page, capabilities, 'the Check my workflows answer')

  await ask(page, 'What needs me?')
  await expect(main(page)).toContainText(/things? needs? you\./)
  await allRules(page, capabilities, 'the What needs me answer')

  await ask(page, 'Every Friday, email me the list of tickets we closed this week')
  await expect(main(page).getByRole('heading', { name: 'I can\'t send email yet' }).last()).toBeVisible()
  await allRules(page, capabilities, 'the can’t answer')

  await ask(page, 'Every Friday at 5pm, find bug tickets in MOCK with no update for 10 days and create one ticket that lists them. Colour them by team.')
  await expect(main(page).locator('section[data-card]').last()).toContainText('I didn’t follow this part.')
  await noPartDropped(page, 'a set-up card with a clause it didn’t follow')
  await allRules(page, capabilities, 'a set-up card with a cross')
  await repair()
  await context.close()
})

/** Principle 4 on the edit card: a part it can't do keeps its cross, and the card never says the whole change is ready while one does. */
async function editKeepsEveryPart(answer: Locator, state: string): Promise<void> {
  await expect(answer.locator('[data-mark="no"]'), `Principle 4 (no part dropped): ${state} shows no cross`).not.toHaveCount(0)
  await expect(answer, `Principle 4: ${state} says the whole change is ready while a part has a cross`).not.toContainText('Nothing changes until you save it.')
}

test('the edit card keeps the design rules in each of its states', async ({ browser, backend }) => {
  const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, { day: 'weekdays', at: '08:00' })
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  const rules = async (state: string) => {
    await onePrimary(page, state)
    await noOverclaim(page, state)
    await noDeadButtons(page, state)
  }

  const hour = await askAndWait(page, `make the ${morning.name} run at 9`)
  await expect(editCard(hour)).toContainText('At 9:00 or 21:00?')
  await rules('the edit card asking for the time')

  const days = await askAndWait(page, `make the ${morning.name} run on Mondays and Thursdays`)
  await expect(editCard(days)).toContainText('I can only set one day.')
  await editKeepsEveryPart(days, 'the edit card with two days')
  await rules('the edit card holding Save for two days')

  const unread = await askAndWait(page, `make the ${morning.name} run on Mondays in the afternoon`)
  await expect(editCard(unread)).toBeVisible()
  await editKeepsEveryPart(unread, 'the edit card with words it didn’t follow')
  await rules('the edit card with a cross')

  const rename = await askAndWait(page, `rename the ${morning.name} to Daily tickets`)
  await expect(rename).toContainText('From the chat I can only change when')
  await rules('the answer to a change the chat can’t make')

  const ready = await askAndWait(page, `make the ${morning.name} run on Mondays only`)
  await expect(editCard(ready)).toContainText('Every Monday at 8:00')
  await rules('the edit card ready to save')
  await editCard(ready).getByRole('button', { name: 'Save change' }).click()
  await expect(editCard(ready)).toContainText('Saved as version 3.')
  await rules('the edit card once saved')
  await editCard(ready).getByRole('button', { name: /^Undo/ }).click()
  await expect(editCard(ready)).toContainText('Undone, as version 4.')
  await rules('the edit card once undone')
  await context.close()
})

const rail = (page: Page) => page.getByRole('navigation', { name: 'Browse' }).filter({ visible: true })

/** The total a rail item's accessible name carries, such as "Watchlist, 6 in all". No count is 0. */
async function railCount(page: Page, label: string): Promise<number> {
  const name = (await rail(page).getByRole('link', { name: new RegExp(`^${label}`) }).getAttribute('aria-label')) ?? ''
  return Number(/, (\d+) in all/.exec(name)?.[1] ?? 0)
}

test('the Needs you rows on Workflows are the number the Planner’s answer and the strip say, the rail shows totals, and the count line is its rows', async ({ browser, backend }) => {
  await backend.waitingRun('alice')
  const repair = await jiraDown(backend)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const total = await needsOnWorkflows(page)
  const { workflows } = await backend.get<{ workflows: number }>('alice', '/api/v1/home')
  expect(await railCount(page, 'Workflows'), 'Principle 7 (one source per fact): the rail’s Workflows count is how many workflows the team has').toBe(workflows)
  expect(await railCount(page, 'Chat'), 'Principle 7: the rail never repeats what needs her').toBe(0)

  await rail(page).getByRole('link', { name: /^Chat/ }).click()
  await ask(page, 'What needs me?')
  await expect(main(page), 'Principle 7: the Planner’s answer').toContainText(`${String(total)} ${total === 1 ? 'thing needs' : 'things need'} you`)
  const strip = main(page).getByRole('region', { name: 'Needs you', exact: true })
  await expect(strip, 'Principle 7: the strip is there while something needs her').toBeVisible()
  const more = (await strip.getByRole('button', { name: /more that need you/ }).count()) === 0 ? 0 : Number((await strip.getByRole('button', { name: /more that need you/ }).innerText()).replace(/\D/g, ''))
  expect(more + 1, 'Principle 7: the strip’s N more plus the one it names is the count everywhere').toBe(total)

  await rail(page).getByRole('link', { name: /^Watchlist/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Watchlist' })).toBeVisible()
  await expect(main(page).getByRole('status').filter({ hasText: /^Loading/ })).toHaveCount(0)
  const watched = await main(page).locator('li[data-status]').count()
  expect(await railCount(page, 'Watchlist'), 'Principle 7: the rail’s Watchlist count is the page’s rows').toBe(watched)
  const line = await main(page).locator('h1 + p').innerText()
  const said = (part: RegExp) => Number(part.exec(line)?.[1] ?? 0)
  const withPill = (...words: readonly string[]) => main(page).locator('li[data-status]').filter({ has: page.locator('span[class*="pill"]').filter({ hasText: new RegExp(`^(${words.join('|')})$`) }) }).count()
  expect(said(/(\d+) ha(?:s|ve) a newer version/), `Principle 7: the count line "${line}" counts every row whose pill says Newer out`).toBe(await withPill('Newer out'))
  expect(said(/(\d+) can’t be found/), `Principle 7: the count line "${line}" counts every row whose pill says Can’t find`).toBe(await withPill('Can’t find'))
  expect(said(/(\d+) can’t be checked/), `Principle 7: the count line "${line}" counts every row whose pill says Can’t check`).toBe(await withPill('Can’t check'))
  expect(said(/(\d+) (?:is|are) up to date/), `Principle 7: the count line "${line}" counts every row whose pill says Up to date`).toBe(await withPill('Up to date'))
  expect(said(/(\d+) watching/), `Principle 7: the count line "${line}" counts every row whose pill says Watching`).toBe(await withPill('Watching'))
  await repair()
  await context.close()
})

test('an Approver who is not an Operator has his Needs you count in his heading, and the rail’s totals with no needs count', async ({ browser, backend }) => {
  await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  const onHome = Number((await main(page).getByRole('heading', { level: 1 }).innerText()).replace(/\D/g, ''))
  expect(onHome, 'his heading counts what needs him').toBeGreaterThan(0)
  expect(await railCount(page, 'Chat'), 'Principle 7: Chat carries no count').toBe(0)
  expect(await railCount(page, 'Workflows'), 'Principle 7: the rail shows the team’s workflows').toBeGreaterThan(0)
  await rail(page).getByRole('link', { name: /^Workflows/ }).click()
  expect(await needsOnWorkflows(page), 'Principle 7: his heading and the Needs you rows on Workflows, with the rest its note counts, agree').toBe(onHome)
  await context.close()
})

test('with the AI model off, Home shows no dead button and still follows the rules', async ({ browser, baseURL }) => {
  const settings = await SettingsApi.connect(String(baseURL))
  try {
    if ((await settings.model()).active !== null) await settings.send('alice', 'DELETE', '/api/v1/settings/model')
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(main(page).getByRole('link', { name: 'Connect a model' })).toBeVisible()
    await allRules(page, [], 'the offline Home')
    await context.close()
  } finally {
    await settings.dispose()
    await connectMockModel(String(baseURL))
  }
})

/** Principles 5 and 7: a declined run never claims a write. No "created", no "Sent" and no ticket link. */
async function noWriteClaimed(scope: Locator, state: string): Promise<void> {
  await expect(scope.first(), `Principles 5 and 7 (a declined run never claims a write): ${state} is not there`).toBeVisible()
  const words = (await scope.allInnerTexts()).join('\n')
  expect(words, `Principles 5 and 7 (a declined run never claims a write): ${state} says "created"`).not.toMatch(/\bcreated\b/i)
  expect(words, `Principle 5 (never claim more than the platform can do): ${state} says "Sent"`).not.toMatch(/\bSent\b/)
  expect(await scope.locator('a[href*="/jira/"]').count(), `Principles 5 and 7: ${state} links a ticket`).toBe(0)
}

test('a declined run never claims a write, on its page, in its chat, on Workflows or on the watchlist', async ({ browser, backend }) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'decline', digest, reason: 'Wrong version' }, undefined, [201])
  await backend.waitForState(runId, ['rejected'])
  for (const user of ['alice', 'bob']) {
    const context = await devContext(browser, user)
    const page = await context.newPage()
    await page.goto(`/runs/${runId}`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Declined, nothing was written')
    await page.locator('summary', { hasText: /what each agent did$/ }).click()
    await expect(page.getByRole('list', { name: 'What the agents said' })).toBeVisible()
    await noWriteClaimed(main(page), `the declined run’s page and chat, as ${user}`)
    await page.goto('/workflows')
    await noWriteClaimed(main(page).locator('li[data-workflow-id]').filter({ hasText: 'Declined by Bob' }), `the declined run’s Workflows row, as ${user}`)
    await page.goto('/software')
    await page.locator('li[data-status="behind"] a').first().click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('LangGraph')
    await noWriteClaimed(main(page).filter({ hasText: 'Declined by Bob.' }), `the software page of the declined check, as ${user}`)
    await context.close()
  }
})

/** The words a state had before the sketch. They are gone from every page, so a state reads one way everywhere. */
const RETIRED_STATE_WORDS = /\bNew version\b|\bNot checked yet\b|\bTicket waiting for a yes\b|\bNothing newer yet\b|\bSoftware we watch\b|\bWaiting on others\b|\bRecent activity\b/

test('Workflows, a workflow, the Watchlist and a software page keep the design rules, and a state reads the same on the list and on the page', async ({ browser, backend }) => {
  await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const rules = async (state: string) => {
    await onePrimary(page, state)
    await noOverclaim(page, state)
    await noDeadButtons(page, state)
    expect(await main(page).innerText(), `Principle 7 (one source per fact): ${state} uses a retired state word`).not.toMatch(RETIRED_STATE_WORDS)
  }

  await page.goto('/workflows')
  const row = main(page).locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })
  await expect(row).toContainText('Waiting for a yes')
  await rules('Workflows')
  const onList = (await row.locator('span[data-life]').innerText()).trim()
  await row.getByRole('link').click()
  await expect(page).toHaveURL(/\/software$/)
  await expect(main(page).locator('li[data-status]').first()).toBeVisible()
  await rules('the Watchlist')

  const pillOf = async (scope: Locator) => (await scope.locator('span[class*="pill"]').first().innerText()).trim()
  const listed = main(page).locator('li[data-status]').first()
  const onWatchlist = await pillOf(listed)
  await listed.getByRole('link').click()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await rules('a software page')
  expect(await pillOf(main(page).locator('div[class*="head"]')), 'Principle 7: a software reads the same on the Watchlist and on its page').toBe(onWatchlist)

  const listedWorkflows = await backend.get<{ use_cases: { use_case_id: string; template: string }[] }>('alice', '/api/v1/use-cases')
  const agent = listedWorkflows.use_cases.find((useCase) => useCase.template !== 'software_watchlist')
  if (agent) {
    await page.goto('/workflows')
    const agentRow = main(page).locator(`li[data-workflow-id="${agent.use_case_id}"]`)
    const rowPill = (await agentRow.locator('span[data-life]').innerText()).trim()
    await agentRow.getByRole('link').click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await rules('a workflow page')
    expect((await main(page).locator('div[class*="head"] span[data-life]').innerText()).trim(), 'Principle 7: a workflow reads the same on Workflows and on its page').toBe(rowPill)
  }
  expect(onList, 'the waiting check reads Waiting for a yes').toBe('Waiting for a yes')
  await context.close()
})
