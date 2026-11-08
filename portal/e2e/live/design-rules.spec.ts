import type { Page } from '@playwright/test'
import { connectMockModel } from './support/settings'
import { SettingsApi } from './support/settings'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext } from './support/ui'

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
const box = (page: Page) => page.getByLabel('Ask the Planner about software versions')

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
  const dead = await main(page).locator('button[aria-disabled="true"]:not([aria-label="Send to the Planner"]), button:disabled:not(textarea)').count()
  expect(dead, `Principle 9 (the person stays in control): ${state} shows ${String(dead)} dead buttons`).toBe(0)
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
  await expect(main(page).getByRole('heading', { name: 'I can' })).toBeVisible()
  await allRules(page, capabilities, 'the abilities answer')

  await ask(page, 'Check my workflows')
  await expect(main(page).getByRole('list', { name: 'Your workflows' })).toBeVisible()
  await allRules(page, capabilities, 'the Check my workflows answer')

  await ask(page, 'What needs me?')
  await expect(main(page)).toContainText(/things? needs? you\./)
  await allRules(page, capabilities, 'the What needs me answer')

  await ask(page, 'Every Friday, email me the list of tickets we closed this week')
  await expect(main(page).getByRole('heading', { name: 'What I can’t do yet' }).last()).toBeVisible()
  await allRules(page, capabilities, 'the can’t answer')
  await repair()
  await context.close()
})

test('the Needs you count is one number on Home, the tab and the Planner’s answer', async ({ browser, backend }) => {
  await backend.waitingRun('alice')
  const repair = await jiraDown(backend)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  const heading = main(page).getByRole('heading', { level: 2, name: /^Needs you/ })
  await expect(heading).toBeVisible()
  const onHome = Number((await heading.innerText()).replace(/\D/g, ''))
  const tab = page.getByRole('navigation', { name: 'Main' }).filter({ visible: true }).getByRole('link', { name: /^Workflows, \d+ need you$/ })
  await expect(tab, 'Principle 7 (one source per fact): the tab count').toHaveAccessibleName(`Workflows, ${String(onHome)} need you`)
  await ask(page, 'What needs me?')
  await expect(main(page), 'Principle 7: the Planner’s answer').toContainText(`${String(onHome)} ${onHome === 1 ? 'thing needs' : 'things need'} you.`)
  await repair()
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
