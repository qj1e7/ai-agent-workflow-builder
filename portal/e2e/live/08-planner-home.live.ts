import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { tabTo, walkTabs, withoutVisibleFocus } from '../support/keyboard'
import { assertClean, watchPage } from '../support/test'
import { connectMockModel } from './support/settings'
import { SettingsApi } from './support/settings'
import { REDIS, type Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

const GREETING = /^Good (morning|afternoon|evening)! Alice$/
const OFFLINE = 'I can’t read new requests until an AI model is connected'

const box = (page: Page) => page.getByLabel('Describe a task for the Planner')
const thread = (page: Page) => page.getByRole('list', { name: 'Conversation with the Planner' })
const polite = (page: Page) => page.locator('[aria-live="polite"]')
const main = (page: Page) => page.getByRole('main')
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().every((animation) => animation.effect?.getComputedTiming().iterations !== Infinity))

async function ask(page: Page, text: string): Promise<void> {
  await box(page).fill(text)
  await box(page).press('Enter')
}

async function modelOff(baseURL: string): Promise<void> {
  const settings = await SettingsApi.connect(baseURL)
  try {
    if ((await settings.model()).active !== null) await settings.send('alice', 'DELETE', '/api/v1/settings/model')
  } finally {
    await settings.dispose()
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

async function noSideways(page: Page): Promise<void> {
  const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
  expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
}

async function tooSmall(controls: Locator): Promise<string[]> {
  const small: string[] = []
  for (const control of await controls.all()) {
    const size = await control.boundingBox()
    if (size && size.height < 43.5) small.push(`${(await control.innerText()).trim() || (await control.getAttribute('aria-label')) || '?'} (${Math.round(size.height)} px)`)
  }
  return small
}

test.describe('with no AI model', () => {
  test.beforeAll(async ({ baseURL }) => {
    await modelOff(String(baseURL))
  })

  test('alice’s Home says it can’t read new requests, offers Connect a model, and keeps the lists, Ask the team and Needs you', async ({ browser, backend }, info) => {
    await backend.waitingRun('alice')
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(OFFLINE)
    await expect(box(page), 'there is no box to type in').toHaveCount(0)
    await expect(main(page).getByRole('link', { name: 'Connect a model' })).toHaveAttribute('href', '/settings?tab=model')
    await expect(main(page).getByRole('heading', { name: 'I can', exact: true })).toBeVisible()
    await expect(main(page).getByRole('button', { name: 'Ask the team for something new' })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Needs you' })).toBeVisible()
    await expect(page.locator('li[data-home-item="connection:model"]'), 'the hero already offers Connect a model').toHaveCount(0)
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), 'planner-home-offline')
    await shot(page, info, 'n10-08-offline')

    await main(page).getByRole('button', { name: 'Ask the team for something new' }).click()
    await page.getByLabel('What should the team know?').fill('Please let the Planner post in Slack')
    await page.getByRole('button', { name: 'Save the request' }).click()
    await expect(main(page)).toContainText('Saved as a request for the team.')
    await main(page).getByRole('link', { name: 'Open it under Following up' }).click()
    await expect(page).toHaveURL(/\/workflows\?request=/)
    assertClean(watch)
    await repair()
    await context.close()
  })

  test('every control on the offline Home does what it says, with no dead button', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(OFFLINE)
    const dead = await main(page).locator('button[aria-disabled="true"], button:disabled, a:not([href])').count()
    expect(dead, 'principle 9: no button is shown dead').toBe(0)
    await context.close()
  })
})

test.describe('with the AI model on', () => {
  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  const SUMMARY = 'Find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
  const card = (page: Page) => thread(page).locator('section[data-card]')
  const left = (page: Page) => card(page).locator('[id$="-left"]')
  const turnOn = (page: Page) => card(page).getByRole('button', { name: 'Turn it on', exact: true })

  /** The card asks for what it lacks, and the plan may ask for the Jira project. Everything is filled from the keyboard. */
  async function fillTheRest(page: Page, project: string): Promise<void> {
    const field = card(page).getByLabel(/^Jira project/)
    if (await field.count()) {
      await field.focus()
      await page.keyboard.type(project)
    }
  }

  // 37 days appears in no other test, so the drafted agent's steps differ from every agent another test saved. The Planner then drafts a new one, whatever the library holds.
  test('inconsistency I6: a new agent is saved to the library only when the workflow is turned on', async ({ browser, backend }, info) => {
    const owner = 'alice'
    const cards = async () => (await backend.get<{ cards: { name: string; owner: string }[] }>(owner, '/api/v1/agent-cards')).cards
    const context = await devContext(browser, owner)
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, 'Every Friday at 4pm, follow up on bug tickets in MOCK with no update for 37 days')
    await expect(card(page)).toBeVisible()
    await card(page).getByRole('button', { name: /what it does|^Create/i }).first().click()
    await card(page).getByRole('group', { name: /^Change/ }).getByRole('textbox').fill('Raise one follow-up ticket that lists them')
    await page.keyboard.press('Enter')
    await card(page).locator('summary').click()
    await expect(card(page).locator('details')).toContainText('New agent, saved to the Agent library when you turn this on', { timeout: 30_000 })
    const before = await cards()
    await fillTheRest(page, 'MOCK')
    await expect(left(page)).toHaveText('Nothing is unclear. Turn it on when you’re ready.', { timeout: 30_000 })
    expect((await cards()).length, 'nothing is saved to the library before Turn it on').toBe(before.length)
    await turnOn(page).click()
    await expect(thread(page).getByRole('status')).toContainText('is saved in the Agent library', { timeout: 30_000 })
    expect((await cards()).length, 'the new agent is in the library after Turn it on').toBe(before.length + 1)
    await shot(page, info, 'n11-i6')
    assertClean(watch)
    await context.close()
  })

  test('scenario D: asking to email a weekly list gets the can’t answer, the Jira ticket alternative and Ask the team', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    await page.route('**/api/v1/planner/answer', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 800))
      await route.continue()
    })
    await ask(page, 'Every Friday, email me the list of tickets we closed this week')
    await expect(box(page), 'the box waits while the Planner answers').toBeDisabled()
    await expect(box(page)).toHaveAttribute('placeholder', 'The Planner is answering')
    await expect(thread(page).getByText('I can’t do all of that, but I can set up something close.')).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can’t do yet' })).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can do instead' })).toBeVisible()
    await expect(thread(page)).toContainText('email')
    await expect(polite(page), 'the sentence is read once, in the polite region').toContainText('I can’t do all of that, but I can set up something close.')
    await expect(box(page)).toBeEnabled()
    await expect(box(page)).toHaveAttribute('placeholder', 'Ask for something else')

    await thread(page).getByRole('button', { name: 'Ask the team' }).click()
    await page.getByLabel('What should the team know?').fill('Please add email so the Planner can send the Friday list')
    await page.getByRole('button', { name: 'Save the request' }).click()
    await expect(thread(page)).toContainText('Saved as a request for the team.')
    await expect(thread(page)).not.toContainText('Sent')
    await shot(page, info, 'n10-08-cant')
    await thread(page).getByRole('link', { name: 'Open it under Following up' }).click()
    await expect(page).toHaveURL(/\/workflows\?request=/)
    await expect(main(page)).toContainText('Please add email')
    assertClean(watch)
    await context.close()
  })

  for (const phone of [false, true]) {
    test(`scenario A: a first-time Operator asks for the weekly follow-up, picks the time the card asks for, turns it on and finds it on Workflows (${phone ? '390' : '1440'} px)`, async ({ browser, backend }, info) => {
      const before = (await backend.get<{ use_cases: { name: string }[] }>('alice', '/api/v1/use-cases')).use_cases.length
      const draftsBefore = (await backend.get<{ drafts: { draft_id: string }[] }>('alice', '/api/v1/drafts')).drafts.map((draft) => draft.draft_id)
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      const watch = watchPage(page)
      await page.goto('/')
      await ask(page, SUMMARY)
      await expect(card(page), 'the Planner answers with a set-up card').toBeVisible()
      await expect(card(page)).toContainText('What will happen')
      await expect(card(page)).toContainText('and put the result in one new Jira ticket')
      await expect(card(page).getByRole('button', { name: /^one new Jira ticket/ }), 'the destination is a visible chip').toBeVisible()
      await expect(card(page).getByRole('button', { name: /^Choose when it runs/ }).first(), 'a time is never guessed').toBeVisible()
      await expect(turnOn(page), 'Turn it on is never shown dead').not.toHaveAttribute('aria-disabled', 'true')
      await expect(left(page)).toContainText(/choices? left: .*when it runs/)
      await shot(page, info, `n11-card-${phone ? '390' : '1440'}`)

      await turnOn(page).focus()
      await page.keyboard.press('Enter')
      const often = card(page).getByLabel('How often')
      await expect(often, 'pressing Turn it on while the time is missing opens the time picker').toBeFocused()
      await expect(card(page).getByText('Choose how often it runs.')).toBeVisible()
      await often.selectOption('week')
      await card(page).getByLabel('Day').selectOption('friday')
      await card(page).getByLabel('Time, Singapore').fill('16:00')
      await expect(card(page)).toContainText('Every week')
      await fillTheRest(page, 'MOCK')
      await expect(left(page), 'the footer recounts from the same list').toHaveText('Nothing is unclear. Turn it on when you’re ready.', { timeout: 30_000 })
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `setup-card-${phone ? '390' : '1440'}`)

      await turnOn(page).focus()
      await page.keyboard.press('Enter')
      await expect(card(page).or(thread(page).getByRole('status')).first()).toBeVisible()
      await expect(thread(page).getByRole('status').getByText(/is on\./)).toBeVisible({ timeout: 30_000 })
      await expect(thread(page).getByRole('button', { name: 'Do a test run' })).toBeVisible()
      await expect(thread(page).getByRole('status')).toContainText('First run')
      await expect(thread(page).getByRole('status')).toContainText('except you is asked for a yes in Teams')
      await shot(page, info, `n11-on-${phone ? '390' : '1440'}`)
      const draftsAfter = (await backend.get<{ drafts: { draft_id: string }[] }>('alice', '/api/v1/drafts')).drafts.map((draft) => draft.draft_id)
      expect(draftsAfter, 'turning it on leaves no new draft behind').toEqual(draftsBefore)

      await thread(page).getByRole('link', { name: 'See it on Workflows' }).click()
      await expect(page).toHaveURL(/\/workflows\/[^/]+$/)
      const after = (await backend.get<{ use_cases: { name: string }[] }>('alice', '/api/v1/use-cases')).use_cases
      expect(after.length, 'one workflow was set up').toBe(before + 1)
      assertClean(watch)
      await context.close()
    })
  }

  test('scenario E: the person changes the guessed project and the schedule without starting again, a change is checked, and the footer recounts', async ({ browser, backend }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, SUMMARY)
    await expect(card(page)).toBeVisible()
    const asked = page.waitForRequest((request) => request.url().endsWith('/api/v1/planner/check-part') && request.method() === 'POST')
    const chip = card(page).getByRole('button', { name: /^bug tickets in MOCK, with no update for 10 days/ })
    await chip.focus()
    await page.keyboard.press('Enter')
    const editor = card(page).getByRole('group', { name: 'Change Looks for' })
    await expect(editor).toBeVisible()
    await editor.getByRole('textbox').fill('bug tickets in OPS, with no update for 10 days')
    await page.keyboard.press('Enter')
    expect((await asked).postDataJSON(), 'a changed part is checked by the Planner').toMatchObject({ kind: 'look_for', text: 'bug tickets in OPS, with no update for 10 days' })
    await expect(card(page).getByRole('button', { name: /^bug tickets in OPS, with no update for 10 days/ }), 'focus and the sentence follow the change').toBeFocused()
    await expect(card(page)).toContainText('find bug tickets in OPS, with no update for 10 days')

    await card(page).getByRole('button', { name: 'Change when it runs' }).click()
    await card(page).getByLabel('How often').selectOption('weekdays')
    await card(page).getByLabel('Time, Singapore').fill('15:00')
    await expect(card(page), 'the sentence follows the schedule').toContainText('Every weekday')
    await expect(left(page)).not.toContainText('when it runs')
    await page.keyboard.press('Escape')

    const drafts = async () => (await backend.get<{ drafts: { draft_id: string; content: { name?: string; form?: { rows: { text: string }[] } } }[] }>('alice', '/api/v1/drafts')).drafts
    await expect.poll(async () => (await drafts()).some((draft) => draft.content.form?.rows.some((row) => row.text === 'bug tickets in OPS, with no update for 10 days')), { message: 'every change is saved as a draft', timeout: 15_000 }).toBe(true)
    await expect(page, 'the draft’s id sits in the address').toHaveURL(/\/\?draft=/)
    const id = new URL(page.url()).searchParams.get('draft') ?? ''

    await page.goto('/workflows')
    const row = page.locator(`li[data-draft="${id}"]`)
    await expect(row, 'the draft shows on Workflows with the card’s own reason').toContainText(/Needs |Nothing is unclear/)
    await row.getByRole('link', { name: /^Resume/ }).click()
    await expect(page, 'Resume reopens the card on Home').toHaveURL(new RegExp(`/\\?draft=${id}`))
    await expect(card(page)).toContainText('find bug tickets in OPS, with no update for 10 days')
    await expect(card(page)).toContainText('Every weekday')
    await shot(page, info, 'n11-resumed')
    await card(page).getByRole('button', { name: 'Rename' }).click()
    await page.getByLabel('Workflow name').fill('Stale bug chaser')
    await page.getByRole('button', { name: 'Done' }).click()
    await expect(card(page).getByRole('heading', { name: 'Stale bug chaser' }).locator('..').getByText('Filled in by me'), 'the tag goes once the person renames').toHaveCount(0)
    await card(page).getByRole('button', { name: 'Never mind' }).click()
    const sure = page.getByRole('alertdialog')
    await expect(sure, 'Never mind on a resumed draft asks first').toBeVisible()
    await sure.getByRole('button', { name: 'Keep the draft' }).click()
    await expect(card(page)).toBeVisible()
    expect((await drafts()).some((draft) => draft.draft_id === id), 'keeping the draft leaves it saved').toBe(true)
    await card(page).getByRole('button', { name: 'Never mind' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Discard draft' }).click()
    await expect(thread(page)).toContainText('All right, never mind.')
    await expect.poll(async () => (await drafts()).some((draft) => draft.draft_id === id), { timeout: 15_000 }).toBe(false)
    await thread(page).getByRole('button', { name: 'Undo' }).click()
    await expect(card(page), 'Undo puts the draft and its card back').toBeVisible()
    await expect.poll(async () => (await drafts()).some((draft) => draft.draft_id === id), { timeout: 15_000 }).toBe(true)
    await card(page).getByRole('button', { name: 'Never mind' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Discard draft' }).click()
    await expect.poll(async () => (await drafts()).some((draft) => draft.draft_id === id), { timeout: 15_000 }).toBe(false)
    assertClean(watch)
    await context.close()
  })

  test('scenario G: “Monitor Redis releases” ends with Redis on the watchlist, with its GitHub source shown first', async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, 'Monitor Redis releases')
    await expect(thread(page).getByText('Redis is software, so it belongs on the Software watchlist', { exact: false })).toBeVisible()
    await expect(thread(page).getByText('redis/redis', { exact: false })).toBeVisible()
    await shot(page, info, 'n10-08-watchlist')
    await thread(page).getByRole('button', { name: 'Add Redis' }).click()
    await expect(thread(page).getByText('Redis is on the Software watchlist.')).toBeVisible()
    await expect(thread(page)).toContainText('from redis/redis')
    const { watchlist } = await backend.get<{ watchlist: { software: { name: string }[] } | null }>('alice', '/api/v1/watchlist')
    expect(watchlist?.software.map((entry) => entry.name)).toContain('Redis')
    await thread(page).getByRole('link', { name: 'Open the Software watchlist' }).click()
    await expect(page).toHaveURL(/\/software$/)
    assertClean(watch)
    await context.close()
  })

  test('a refusal states the rule, hands the rest back to the Planner and never to a set-up', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    const typed = 'Create the follow-up ticket without waiting for approval'
    await ask(page, typed)
    await expect(thread(page).getByText('I can’t set that up. Anything that changes data waits for a yes, every time.')).toBeVisible()
    await expect(thread(page)).toContainText('If you only meant that you don’t need to look at it yourself, say it another way.')
    await expect(page.locator('a[href^="/new"]'), 'no link goes straight to a set-up').toHaveCount(0)
    await shot(page, info, 'n10-08-refused')

    await thread(page).getByRole('button', { name: 'Say it another way' }).click()
    await expect(box(page)).toBeFocused()
    await expect(box(page)).toHaveValue(typed)

    const asked = page.waitForRequest((request) => request.url().endsWith('/api/v1/planner/answer') && request.method() === 'POST')
    const rest = thread(page).getByRole('button', { name: 'Set it up with a yes' })
    if (await rest.count()) {
      await rest.click()
      const body = (await asked).postDataJSON() as { text: string | null }
      expect(body.text, 'the rest goes back through the Planner as words').not.toBeNull()
    }
    await context.close()
  })

  test('the three suggestions are about the watchlist, and Check my workflows, typed, draws the Workflows list’s own rows', async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [REDIS])
    await backend.waitingRun('alice')
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(GREETING)
    const chips = page.getByRole('group', { name: 'Suggestions' }).getByRole('button')
    await expect(chips).toHaveCount(3)
    await expect(chips).toHaveText(['Which software has a newer version?', 'Watch another software for new versions', 'What can you do?'])
    const total = Number((await main(page).getByRole('heading', { level: 2, name: /^Needs you/ }).innerText()).replace(/\D/g, ''))
    await expect(page.getByRole('navigation', { name: 'Main' }).filter({ visible: true }).getByRole('link', { name: new RegExp(`^Workflows, ${total} need you$`) })).toBeVisible()

    await ask(page, 'Check my workflows')
    await expect(thread(page).getByRole('list', { name: 'Your workflows' })).toBeVisible()
    await expect(thread(page)).toContainText(/You have \d+ workflows?\./)
    await expect(main(page).getByRole('heading', { level: 2, name: /^Needs you/ }), 'Needs you is hidden while the thread shows').toHaveCount(0)
    await shot(page, info, 'n10-08-check')

    await ask(page, 'What needs me?')
    await expect(thread(page)).toContainText(`${total} ${total === 1 ? 'thing needs' : 'things need'} you.`)
    await page.getByRole('button', { name: 'New chat' }).click()
    await expect(thread(page)).toHaveCount(0)
    await expect(main(page).getByRole('heading', { level: 2, name: new RegExp(`^Needs you ${total}`) })).toBeVisible()
    assertClean(watch)
    await repair()
    await context.close()
  })

  test('Enter sends from the box and the whole task works by keyboard', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await box(page).focus()
    await page.keyboard.type('What can you do?')
    await page.keyboard.press('Enter')
    await expect(thread(page).getByText('Here is what I can do, and what I can’t do yet.')).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'I can', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'New chat' }).focus()
    await page.keyboard.press('Enter')
    await expect(thread(page)).toHaveCount(0)
    await context.close()
  })

  test('the chip Which software has a newer version? is answered from the watchlist, with its Looked at line', async ({ browser, backend }) => {
    await backend.freshWatchlist('alice', [REDIS])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await page.getByRole('group', { name: 'Suggestions' }).getByRole('button', { name: 'Which software has a newer version?' }).click()
    await expect(thread(page)).toContainText('Nothing on your watchlist has a newer version.')
    await expect(thread(page).getByText('Looked at')).toBeVisible()
    await expect(thread(page).getByRole('link', { name: 'Software', exact: true })).toBeVisible()
    await context.close()
  })

  test('by keyboard alone: Tab reaches the box, the suggestions and each answer’s buttons, with a visible focus ring', async ({ browser, backend }) => {
    await backend.freshWatchlist('alice', [REDIS])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    const walk = await walkTabs(page)
    const labels = walk.stops.map((stop) => stop.label)
    for (const name of ['Describe a task for the Planner', 'Send to the Planner', 'Which software has a newer version?']) {
      expect(labels.some((label) => label.includes(name)), `Tab reaches ${name}; stops: ${labels.join(', ')}`).toBe(true)
    }
    expect(walk.unreached, 'controls Tab never reached').toEqual([])
    expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing').toEqual([])

    await tabTo(page, page.getByRole('button', { name: 'Watch another software for new versions' }))
    await page.keyboard.press('Enter')
    await expect(thread(page)).toContainText(/software/i)
    await ask(page, 'Every Friday, email me the list of tickets we closed this week')
    await tabTo(page, thread(page).getByRole('button', { name: 'Ask the team' }))
    await page.keyboard.press('Enter')
    await expect(page.getByLabel('What should the team know?')).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Save the request' })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(thread(page)).toContainText('Saved as a request for the team.')
    await context.close()
  })

  for (const phone of [false, true]) {
    const size = phone ? '390' : '1440'
    test(`Home and its answers pass WCAG 2.2 AA, do not scroll sideways and keep 44 px targets at ${size} px`, async ({ browser, backend }, info) => {
      await backend.waitingRun('alice')
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      await page.goto('/')
      await expect(box(page)).toBeVisible()
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `planner-home-${size}`)
      await noSideways(page)
      expect(await tooSmall(main(page).locator('button, a[href]')), 'principle 11: targets of at least 44 px').toEqual([])
      await shot(page, info, `n10-08-home-${size}`)

      for (const [text, shown] of [
        ['Check my workflows', thread(page).getByRole('list', { name: 'Your workflows' })],
        ['What can you do?', thread(page).getByRole('heading', { name: 'I can', exact: true })],
        ['Every Friday, email me the list of tickets we closed this week', thread(page).getByRole('heading', { name: 'What I can’t do yet' })],
      ] as const) {
        await ask(page, text)
        await expect(shown.first()).toBeVisible()
      }
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `planner-thread-${size}`)
      await noSideways(page)
      await shot(page, info, `n10-08-thread-${size}`)
      await context.close()
    })
  }

  test('with reduced motion no loop runs on Home, the Planner’s face or the thinking dots', async ({ browser }) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    await ask(page, 'Check my workflows')
    await expect(thread(page)).toContainText(/You have \d+ workflows?\./)
    const running = await page.evaluate(() => document.getAnimations().filter((animation) => animation.playState === 'running' && animation.effect?.getComputedTiming().iterations === Infinity).length)
    expect(running, 'no infinite animation is running').toBe(0)
    await context.close()
  })

  test('the old New workflow address leads to Home and never to a blank page', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('link', { name: 'New workflow' })).toHaveCount(0)
    for (const old of ['/new', '/new/done/uc_1']) {
      await page.goto(old)
      await expect(page).toHaveURL(/\/$/)
      await expect(page.getByLabel('Describe a task for the Planner')).toBeVisible()
    }
    await context.close()
  })

  test('the old address of a saved draft reopens that draft as a card on Home', async ({ browser, backend }) => {
    const id = randomUUID()
    const text = `Every Monday, list the tickets closed last week ${id.slice(0, 6)}`
    const content = {
      name: `Old address draft ${id.slice(0, 6)}`,
      form: {
        step: 2,
        text,
        name: '',
        rows: [
          { kind: 'schedule', text: 'Every Monday', state: 'understood', note: null },
          { kind: 'look_for', text: 'tickets closed last week in MOCK', state: 'understood', note: null },
          { kind: 'do', text: 'Create one ticket that lists them', state: 'understood', note: null },
          { kind: 'where', text: 'Jira project MOCK', state: 'understood', note: null },
        ],
        typed: {},
        when: { often: '', at: '' },
      },
      plan: null,
    }
    const saved = await backend.send('PUT', 'alice', `/api/v1/drafts/${id}`, { step: 2, content })
    expect(saved.status, `alice saves a draft: ${JSON.stringify(saved.body)}`).toBe(200)
    const context = await devContext(browser, 'alice')
    try {
      const page = await context.newPage()
      await page.goto(`/new?draft=${id}`)
      await expect(thread(page).locator('section[data-card]')).toContainText('tickets closed last week')
      await expect(page).toHaveURL(new RegExp(`/\\?draft=${id}$`))
    } finally {
      await context.close()
      await backend.send('DELETE', 'alice', `/api/v1/drafts/${id}`)
    }
  })

  test('the old address of a draft that is gone says so, and Home stays usable', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto(`/new?draft=${randomUUID()}`)
    await expect(main(page)).toContainText('That draft is gone. Ask for it again below.')
    await expect(box(page)).toBeVisible()
    await context.close()
  })
})

test('bob’s Home has no box, no suggestions and no creation action', async ({ browser, backend }) => {
  await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(page.getByRole('list', { name: 'Needs you' })).toBeVisible()
  await expect(main(page)).toContainText('You’re an Approver, so you decide on requests. Operators set up workflows.')
  await expect(page.getByLabel('Describe a task for the Planner')).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Suggestions' })).toHaveCount(0)
  await context.close()
})
