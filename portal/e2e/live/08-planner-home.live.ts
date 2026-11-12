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
/** A request the Planner answers with a set-up card. */
const SUMMARY = 'Find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'

const box = (page: Page) => page.getByLabel('Ask the Planner about software versions')
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

/** The number every place shows for Needs you, read from the platform: each kind it counts, added up. */
async function platformNeeds(backend: Backend, user: string): Promise<number> {
  const home = await backend.get<{ approvals_total: number; stopped_total: number; confirmations: unknown[]; connections: unknown[]; addresses: unknown[]; replied: unknown[] }>(user, '/api/v1/home')
  return home.approvals_total + home.stopped_total + home.confirmations.length + home.connections.length + home.addresses.length + home.replied.length
}

/** Alice asks the team for something and bob replies, so the reply sits in her Needs you until she opens it. */
async function teamReplied(backend: Backend): Promise<void> {
  const made = await backend.post<{ request_id: string }>('alice', '/api/v1/team-requests', { kind: 'ask_the_team', about: { capability: 'email.send' }, note: `Please add email ${randomUUID().slice(0, 6)}` }, { 'Idempotency-Key': randomUUID() }, [201])
  await backend.post('bob', `/api/v1/team-requests/${made.request_id}/replies`, { text: 'Not on the plan yet, we will tell you.' }, undefined, [201])
}

/** A draft alice saved from a set-up card, which Resume reopens as that card. */
async function cardDraft(backend: Backend, label: string): Promise<string> {
  const id = randomUUID()
  const content = {
    name: `${label} ${id.slice(0, 6)}`,
    form: {
      step: 2,
      text: `Every Monday, list the tickets closed last week ${id.slice(0, 6)}`,
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
  return id
}

/** Every draft saved from this page, with the person it was saved as. */
function draftSaves(page: Page): string[] {
  const saves: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'PUT' && /\/api\/v1\/drafts\//.test(request.url())) saves.push(request.headers()['x-dev-user'] ?? 'unknown')
  })
  return saves
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

  test('alice’s Home says it can’t read new requests, offers Connect a model, and keeps the lists and Needs you, the model row first and counted (FIX-offline-count)', async ({ browser, backend }, info) => {
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
    await expect(main(page).getByRole('button', { name: 'Ask the team for something new' }), 'Home offers no request for the team').toHaveCount(0)
    const needs = page.getByRole('list', { name: 'Needs you' })
    await expect(needs.locator('li[data-home-item]').first(), 'FIX-offline-count: the first row is the model').toHaveAttribute('data-home-item', 'connection:model')
    await expect(needs.locator('li[data-home-item="connection:model"]'), 'it points to the button above it').toHaveText(/No AI model connected\s*Connect one with the button above\./)
    await expect(needs.locator('li[data-home-item="connection:model"]').getByRole('link'), 'it offers no second Connect a model').toHaveCount(0)
    await expect(main(page).getByRole('link', { name: 'Connect a model' }), 'the hero has the only Connect a model').toHaveCount(1)
    const counted = await platformNeeds(backend, 'alice')
    expect(counted, 'the platform counts the model row with the rest').toBeGreaterThan(1)
    await expect(page.getByRole('heading', { name: /^Needs you/, level: 2 }), 'FIX-offline-count: the number is the platform’s count, the model row included').toHaveText(new RegExp(`^Needs you\\s*${String(counted)}$`))
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), 'planner-home-offline')
    await shot(page, info, 'n10-08-offline')

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
    await expect(card(page).locator('details')).toContainText('New agent, saved under How it works, in Settings, when you turn this on', { timeout: 30_000 })
    const before = await cards()
    await fillTheRest(page, 'MOCK')
    await expect(left(page)).toHaveText('Nothing is unclear. Turn it on when you’re ready.', { timeout: 30_000 })
    expect((await cards()).length, 'nothing is saved to the library before Turn it on').toBe(before.length)
    await turnOn(page).click()
    await expect(thread(page).getByRole('status')).toContainText('is saved under How it works, in Settings', { timeout: 30_000 })
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

      await thread(page).getByRole('button', { name: 'Do a test run' }).click()
      await expect(page).toHaveURL(/\/runs\/run_/, { timeout: 30_000 })
      const after = (await backend.get<{ use_cases: { name: string; last_run: { test: boolean } | null }[] }>('alice', '/api/v1/use-cases')).use_cases
      expect(after.length, 'one workflow was set up').toBe(before + 1)
      expect(after[0]?.last_run?.test, 'Do a test run records a test run').toBe(true)
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

  for (const phone of [false, true]) {
    const size = phone ? '390' : '1440'
    test(`a follow-up about watched software is answered from the watchlist, with the Software page’s own actions behind it at ${size} px`, async ({ browser, backend }, info) => {
      await backend.freshWatchlist('alice', [REDIS])
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      await page.goto('/')
      await ask(page, 'How many software are we watching?')
      await expect(thread(page)).toContainText('Your watchlist holds 1 software.')
      await ask(page, 'what about Redis?')
      await expect(thread(page)).toContainText('Redis runs 8.2.0.')
      await expect(thread(page).getByText('Looked at').last()).toBeVisible()
      const open = thread(page).getByRole('button', { name: 'Open Redis on the Software page' })
      await expect(open, 'from the chat it opens in the side panel').toHaveAttribute('data-opens', /^software:/)
      const stop = thread(page).getByRole('button', { name: 'Stop watching Redis' })
      await expect(stop, 'Stop watching comes after Open').toBeVisible()
      const check = thread(page).getByRole('button', { name: 'Check all software now' })
      await expect(check).toBeVisible()
      expect(await tooSmall(open), 'principle 11: targets of at least 44 px').toEqual([])
      expect(await tooSmall(stop.or(check)), 'principle 11: targets of at least 44 px').toEqual([])
      await noSideways(page)
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `2b-follow-up-${size}`)
      await shot(page, info, `2b-follow-up-${size}`)

      await stop.click()
      await expect(thread(page)).toContainText('Stop watching Redis? It won’t be checked any more.')
      await expect(thread(page).getByRole('button', { name: 'Keep it on the watchlist' }), 'focus lands on the safe choice').toBeFocused()
      await thread(page).getByRole('button', { name: 'Keep it on the watchlist' }).click()
      const names = async () => (await backend.get<{ watchlist: { software: { name: string }[] } | null }>('alice', '/api/v1/watchlist')).watchlist?.software.map((entry) => entry.name)
      expect(await names(), 'asking and keeping removes nothing').toContain('Redis')

      await stop.click()
      await thread(page).getByRole('button', { name: 'Yes, stop watching Redis' }).click()
      await expect(thread(page)).toContainText('Removed Redis. It won’t be checked any more.')
      expect(await names()).not.toContain('Redis')
      await thread(page).getByRole('button', { name: 'Undo' }).click()
      await expect(thread(page)).toContainText('Put Redis back on the list.')
      expect(await names(), 'the page’s Undo puts it back').toContain('Redis')

      await open.click()
      await expect(page).toHaveURL(/\/software\?row=/)
      await context.close()
    })
  }

  test('an unwatched name after a question is offered for the watchlist, never added on its own', async ({ browser, backend }) => {
    await backend.freshWatchlist('alice', [REDIS])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await ask(page, 'How many software are we watching?')
    await expect(thread(page)).toContainText('Your watchlist holds 1 software.')
    await ask(page, 'and Grafana?')
    await expect(thread(page)).toContainText('Grafana')
    const { watchlist } = await backend.get<{ watchlist: { software: { name: string }[] } | null }>('alice', '/api/v1/watchlist')
    expect(watchlist?.software.map((entry) => entry.name)).toEqual(['Redis'])
    await context.close()
  })

  test('by keyboard alone: Tab reaches the box, the suggestions and each answer’s buttons, with a visible focus ring', async ({ browser, backend }) => {
    await backend.freshWatchlist('alice', [REDIS])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    // The suggestions draw once the watchlist and the registry have loaded, so the walk waits for the ones it checks.
    await expect(page.getByRole('group', { name: 'Suggestions' }).getByRole('button')).toHaveCount(3)
    const walk = await walkTabs(page)
    const labels = walk.stops.map((stop) => stop.label)
    for (const name of ['Ask the Planner about software versions', 'Send to the Planner', 'Which software has a newer version?']) {
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
      await expect(page.getByLabel('Ask the Planner about software versions')).toBeVisible()
    }
    await context.close()
  })

  test('the old address of a saved draft reopens that draft as a card on Home', async ({ browser, backend }) => {
    const id = await cardDraft(backend, 'Old address draft')
    const context = await devContext(browser, 'alice')
    try {
      const page = await context.newPage()
      await page.goto(`/new?draft=${id}`)
      await expect(thread(page).locator('section[data-card]')).toContainText('tickets closed last week')
      await expect(page, 'once the card is open, the address no longer asks for the draft').toHaveURL(/\/$/)
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

test.describe('the chat after the first message', () => {
  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  const pinned = (page: Page) => page.getByRole('region', { name: 'Most urgent' })
  const pinnedOpen = (page: Page) => pinned(page).getByRole('link', { name: /^Open/ }).or(pinned(page).getByRole('button', { name: /^Open/ }))
  const needsTotal = async (page: Page) =>
    Number(((await page.getByRole('navigation', { name: 'Main' }).filter({ visible: true }).getByRole('link', { name: /^Workflows, \d+ need you$/ }).getAttribute('aria-label')) ?? '').replace(/\D/g, ''))

  test('SHELL-pinned: the pinned line appears with the first message, the box docks, and N more plus one is the count everywhere', async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [REDIS])
    await teamReplied(backend)
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    await expect(pinned(page), 'no pinned line before the first message').toHaveCount(0)
    await ask(page, 'What can you do?')
    await expect(pinned(page)).toBeVisible()
    await expect(box(page)).toHaveAttribute('placeholder', 'Ask for something else')
    await expect(box(page), 'an answer with no card hands focus back to the box').toBeFocused()
    await expect(main(page).getByRole('heading', { level: 2, name: /^Needs you/ }), 'Needs you gives way to the pinned line').toHaveCount(0)
    const total = await needsTotal(page)
    expect(total, 'a reply from the team and Jira not answering are two needs').toBeGreaterThan(1)
    expect(total, 'the rail’s count is the platform’s').toBe(await platformNeeds(backend, 'alice'))
    await expect(pinnedOpen(page), 'Open shows a stop or a request in the side panel, and anything else on its page').toBeVisible()
    if ((await pinned(page).getByRole('link', { name: /^Open/ }).count()) > 0) await expect(pinned(page).getByRole('link', { name: /^Open/ })).toHaveAttribute('href', /^\/(settings|software|workflows)/)
    else await expect(pinned(page).getByRole('button', { name: /^Open/ })).toHaveAttribute('data-opens', /^run:/)
    await expect(pinned(page).getByRole('link', { name: `${String(total - 1)} more that need you` })).toHaveAttribute('href', '/workflows')
    await pinned(page).getByRole('link', { name: /more that need you/ }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    await expect(main(page).getByRole('heading', { level: 2, name: new RegExp(`^Needs you ${String(total)}`) })).toBeVisible()
    await expect(main(page).getByRole('heading', { level: 3, name: 'Do now' })).toBeVisible()
    await page.getByRole('link', { name: 'Back to the chat' }).click()
    await expect(thread(page)).toContainText('What can you do?')
    await expect(pinned(page)).toBeVisible()
    await shot(page, info, 'r2-chat-pinned')
    await repair()
    await context.close()
  })

  test('SHELL-rail: the rail brings the chat back as it was, scroll position included', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.setViewportSize({ width: 1280, height: 520 })
    await page.goto('/')
    for (const words of ['What can you do?', 'Check my workflows', 'What needs me?']) await ask(page, words)
    await expect(thread(page)).toContainText(/things? needs? you\./)
    const conversation = page.getByRole('region', { name: 'Conversation' })
    await expect(conversation, 'a conversation that overflows is a Tab stop, so the keyboard can scroll it').toHaveAttribute('tabindex', '0')
    await conversation.evaluate((element) => {
      element.scrollTop = 120
    })
    const before = await conversation.evaluate((element) => element.scrollTop)
    expect(before).toBeGreaterThan(0)
    const rail = page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })
    await rail.getByRole('link', { name: /^Workflows/ }).click()
    await expect(thread(page)).toHaveCount(0)
    await rail.getByRole('link', { name: /^Chat/ }).click()
    await expect(thread(page)).toContainText('Check my workflows')
    await expect.poll(() => conversation.evaluate((element) => element.scrollTop)).toBe(before)
    await context.close()
  })

  test('ASK-needs: the answer counts what needs her, with one row each, and agrees with the rail', async ({ browser, backend }) => {
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await ask(page, 'What needs me?')
    const total = await needsTotal(page)
    await expect(thread(page)).toContainText(`${String(total)} ${total === 1 ? 'thing needs' : 'things need'} you.`)
    await expect(thread(page).locator('li[data-home-item]')).toHaveCount(total)
    await repair()
    await context.close()
  })

  test('a short conversation is no Tab stop, because there is nothing to scroll', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.route('**/api/v1/planner/answer', (route) => route.fulfill({ json: { answer: 'which_software', word: 'version' } }))
    await page.goto('/')
    await ask(page, 'Is there a newer version?')
    await expect(thread(page)).toContainText('Which software should I watch?')
    await expect(page.getByRole('region', { name: 'Conversation' })).not.toHaveAttribute('tabindex')
    await context.close()
  })

  test('Resume on Workflows with a conversation open adds the draft’s card after it, with focus on the card', async ({ browser, backend }) => {
    const id = await cardDraft(backend, 'Resume in chat')
    const context = await devContext(browser, 'alice')
    try {
      const page = await context.newPage()
      await page.goto('/')
      await ask(page, 'What can you do?')
      await expect(thread(page).locator('li[data-answer]')).toHaveCount(1)
      const rail = page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })
      await rail.getByRole('link', { name: /^Workflows/ }).click()
      await page.locator(`li[data-draft="${id}"]`).getByRole('link', { name: /^Resume/ }).click()
      const resumed = thread(page).locator('section[data-card]')
      await expect(resumed).toContainText('tickets closed last week')
      await expect(thread(page), 'the conversation before it stays').toContainText('What can you do?')
      await expect(resumed.getByRole('heading', { level: 3 }).first(), 'focus goes to the card').toBeFocused()
      await expect(page, 'the address no longer asks for the draft').toHaveURL(/\/$/)
    } finally {
      await context.close()
      await backend.send('DELETE', 'alice', `/api/v1/drafts/${id}`)
    }
  })

  test('a card keeps what she did on it across pages, and New chat saves it once as her draft and says so', async ({ browser, backend }) => {
    const name = `Kept card ${randomUUID().slice(0, 6)}`
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const saves = draftSaves(page)
    await page.goto('/')
    await ask(page, SUMMARY)
    const card = thread(page).locator('section[data-card]')
    await expect(card.getByRole('heading', { level: 3 }).first(), 'a set-up card takes focus at its heading').toBeFocused()
    await card.getByRole('button', { name: /^Rename/ }).click()
    await card.getByLabel('Workflow name').fill(name)
    await page.keyboard.press('Enter')
    await expect(page, 'the card saves her change as a draft').toHaveURL(/\?draft=/)
    const draftId = new URL(page.url()).searchParams.get('draft') ?? ''
    const rail = page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })
    await rail.getByRole('link', { name: /^Workflows/ }).click()
    await rail.getByRole('link', { name: /^Chat/ }).click()
    await expect(card.getByRole('heading', { level: 3, name }), 'the card comes back as she left it').toBeVisible()
    const before = saves.length
    await page.getByRole('button', { name: 'New chat' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Your draft is saved. Find it on Workflows.' })).toBeVisible()
    await expect.poll(() => saves.length, { message: 'New chat saves the card' }).toBeGreaterThan(before)
    await page.waitForTimeout(1_000)
    expect(saves.slice(before), 'New chat saves the card once, as alice').toEqual(['alice'])
    const drafts = await backend.get<{ drafts: { draft_id: string; content: unknown }[] }>('alice', '/api/v1/drafts')
    expect(drafts.drafts.filter((draft) => JSON.stringify(draft.content).includes(name)).map((draft) => draft.draft_id), 'one draft, the card’s own').toEqual([draftId])
    await context.close()
    await backend.send('DELETE', 'alice', `/api/v1/drafts/${draftId}`)
  })

  test('a card she hadn’t finished is never saved as the next person who signs in', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const saves = draftSaves(page)
    await page.goto('/')
    await ask(page, 'Every Friday at 4pm, follow up on bug tickets in MOCK with no update for 41 days')
    await expect(thread(page).locator('section[data-card]')).toBeVisible()
    await page.getByRole('button', { name: /Test controls/ }).click()
    await page.getByRole('button', { name: 'Bob', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Bob')
    await page.waitForTimeout(1_000)
    expect(saves, 'no draft is saved as bob').not.toContain('bob')
    await page.getByRole('button', { name: 'Alice', exact: true }).click()
    await expect(thread(page).locator('section[data-card]'), 'her card is there when she comes back').toBeVisible()
    await context.close()
  })

  test('a workflow a chat card opens in the side panel has More details, a page with Back to the chat, which puts focus back on the chat', async ({ browser, backend }) => {
    const name = `Back to the chat ${randomUUID().slice(0, 6)}`
    await backend.post('alice', '/api/v1/agent-use-cases', { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }] }, undefined, [201])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await ask(page, 'Check my workflows')
    await thread(page).getByRole('list', { name: 'Your workflows' }).getByRole('button', { name, exact: true }).click()
    await page.locator('#side-panel').getByRole('link', { name: 'More details' }).click()
    await expect(page.getByRole('link', { name: 'Back to the chat' })).toBeVisible()
    await expect(main(page).getByRole('link', { name: 'Workflows', exact: true }), 'the page’s own Back gives way to Back to the chat').toHaveCount(0)
    await page.getByRole('link', { name: 'Back to the chat' }).click()
    await expect(thread(page)).toContainText('Check my workflows')
    await expect(page.getByRole('heading', { level: 1, name: 'Planner' })).toBeFocused()
    await expect(page.locator('#side-panel'), 'the panel is still there on return').toBeVisible()
    await context.close()
  })

  test('ROLE-own-chat: signing in as someone else never shows the last person’s chat, and hers is there when she comes back', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await ask(page, 'Check my workflows')
    await expect(thread(page)).toContainText('Check my workflows')
    await page.getByRole('button', { name: /Test controls/ }).click()
    await page.getByRole('button', { name: 'Bob', exact: true }).click()
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Bob')
    await expect(thread(page)).toHaveCount(0)
    await expect(main(page)).not.toContainText('Check my workflows')
    await page.getByRole('button', { name: 'Alice', exact: true }).click()
    await expect(thread(page)).toContainText('Check my workflows')
    await context.close()
  })

  test('FIX-starts-count: the sentence over the places to start counts the places it shows', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.route('**/api/v1/planner/answer', (route) => route.fulfill({ json: { answer: 'ideas' } }))
    await page.goto('/')
    await ask(page, 'set up another workflow')
    const uses = thread(page).getByRole('button', { name: 'Use this' })
    await expect(uses.first(), 'the places to start are drawn before they are counted').toBeVisible()
    const places = await uses.count()
    await expect(thread(page)).toContainText(places === 1 ? 'Here is a place to start. Pick it, or tell me something else.' : `Here are ${String(places)} places to start. Pick one, or tell me something else.`)
    await context.close()
  })

  test('New chat clears the thread and brings back Needs you in place of the pinned line, and the keyboard reaches the box, New chat and the pinned line', async ({ browser, backend }) => {
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await ask(page, 'What can you do?')
    await tabTo(page, pinnedOpen(page))
    await tabTo(page, page.getByRole('button', { name: 'New chat' }))
    await page.keyboard.press('Enter')
    await expect(thread(page)).toHaveCount(0)
    await expect(pinned(page)).toHaveCount(0)
    await expect(main(page).getByRole('heading', { level: 2, name: /^Needs you/ })).toBeVisible()
    await expect(box(page)).toBeFocused()
    await repair()
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
  await expect(page.getByLabel('Ask the Planner about software versions')).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Suggestions' })).toHaveCount(0)
  await context.close()
})
