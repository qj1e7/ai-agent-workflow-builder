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
import { askAndWait, editCard, newestAnswer, rereadOf, scheduledWorkflow, shown, tag, versionsOf } from './support/edit'

/** The sketch's question, Alice's Home heading; her greeting is the line above it. */
const ALICE_HEADING = 'What should run by itself?'
const OFFLINE = 'I can’t read new requests until an AI model is connected'
/** A request the Planner answers with a set-up card. */
const SUMMARY = 'Find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'

const box = (page: Page) => page.getByLabel('Ask, or describe a task')
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
  const home = await backend.get<{ approvals_total: number; stopped_total: number; declined_total: number; questions_for_me_total: number; confirmations: unknown[]; connections: unknown[]; addresses: unknown[]; replied: unknown[] }>(user, '/api/v1/home')
  return home.approvals_total + home.stopped_total + home.declined_total + home.questions_for_me_total + home.confirmations.length + home.connections.length + home.addresses.length + home.replied.length
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

const draftIds = async (backend: Backend): Promise<string[]> => (await backend.get<{ drafts: { draft_id: string }[] }>('alice', '/api/v1/drafts')).drafts.map((draft) => draft.draft_id)

/** Deletes the drafts a test's cards saved as newer answers replaced them, so alice's draft limit never stops a later test. */
async function forgetNewDrafts(backend: Backend, before: readonly string[]): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 1_500))
  for (const id of await draftIds(backend)) if (!before.includes(id)) await backend.send('DELETE', 'alice', `/api/v1/drafts/${id}`)
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
    if (size && size.height < 24) small.push(`${(await control.innerText()).trim() || (await control.getAttribute('aria-label')) || '?'} (${Math.round(size.height)} px)`)
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
  test('ROLE-offline: bob’s Home says the Planner can’t answer and who can connect one, with no box, and keeps his request first', async ({ browser, backend }, info) => {
    await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('I can’t answer questions until an AI model is connected')
    await expect(main(page)).toContainText(/An Operator can connect one in Settings\. (\d+ requests? (is|are) waiting for your yes|\d+ things? needs? you)\./)
    await expect(page.getByRole('textbox'), 'no box while there is no model').toHaveCount(0)
    await expect(main(page).getByRole('link', { name: 'Connect a model' }), 'no Connect a model, which only an Operator can use').toHaveCount(0)
    await expect(page.getByRole('list', { name: 'Needs you' }).getByRole('link', { name: 'Review and decide' }).first()).toBeVisible()
    await shot(page, info, 'r16-bob-offline')
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

  /** The card asks for what it lacks, and the plan may ask for the Jira project. Everything is filled from the keyboard, and a project the Planner already filled in is left as it is. */
  async function fillTheRest(page: Page, project: string): Promise<void> {
    const field = card(page).last().getByLabel(/^Jira project/)
    if ((await field.count()) && (await field.inputValue()) === '') {
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
    await ask(page, 'Every Friday at 4pm, find bug tickets in MOCK with no update for 37 days')
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
    await expect(box(page), 'the box waits while the Planner answers, with the sketch’s one placeholder').toBeDisabled()
    await expect(thread(page).getByText('I can’t do all of that, but I can set up something close.')).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can’t do yet' })).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can do instead' })).toBeVisible()
    await expect(thread(page)).toContainText('email')
    await expect(polite(page), 'the sentence is read once, in the polite region').toContainText('I can’t do all of that, but I can set up something close.')
    await expect(box(page)).toBeEnabled()
    await expect(box(page)).toHaveAttribute('placeholder', 'Ask, or describe a task')

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
      const parts = card(page).getByRole('list', { name: 'Each part of your request' })
      await expect(parts.locator('[data-part="dest"]')).toContainText('one new Jira ticket')
      await expect(card(page).getByRole('button', { name: /^one new Jira ticket/ }), 'the destination is a visible chip').toBeVisible()
      await expect(parts.locator('[data-mark="ask"]'), 'one question at a time').toHaveCount(1)
      await expect(parts.locator('[data-part="when"]'), 'a time is never guessed: it asks how often first').toContainText('How often should it run?')
      await expect(turnOn(page), 'Turn it on is never shown dead').not.toHaveAttribute('aria-disabled', 'true')
      await expect(left(page)).toContainText(/choices? left: .*when it runs/)
      await shot(page, info, `n11-card-${phone ? '390' : '1440'}`)

      await turnOn(page).focus()
      await page.keyboard.press('Enter')
      const weekly = card(page).getByRole('button', { name: 'Every week', exact: true })
      await expect(card(page).getByRole('button', { name: 'Every day', exact: true }), 'pressing Turn it on while the time is missing goes to the question').toBeFocused()
      await weekly.click()
      await expect(parts.locator('[data-part="when"]')).toContainText('Which day should it run?')
      await card(page).getByRole('button', { name: 'Friday', exact: true }).click()
      await expect(parts.locator('[data-part="when"]')).toContainText('What time should it run?')
      await card(page).getByRole('button', { name: '17:00', exact: true }).click()
      await expect(parts.locator('[data-part="when"]')).toContainText('Every Friday at 17:00, Singapore time')
      await expect(parts.locator('[data-part="when"]')).toHaveAttribute('data-mark', 'ok')
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
    const editor = card(page).getByRole('group', { name: 'Change Which tickets' })
    await expect(editor).toBeVisible()
    await editor.getByRole('textbox').fill('bug tickets in OPS, with no update for 10 days')
    await page.keyboard.press('Enter')
    expect((await asked).postDataJSON(), 'a changed part is checked by the Planner').toMatchObject({ kind: 'look_for', text: 'bug tickets in OPS, with no update for 10 days' })
    await expect(card(page).getByRole('button', { name: /^bug tickets in OPS, with no update for 10 days/ }), 'focus and the sentence follow the change').toBeFocused()
    await expect(card(page)).toContainText('bug tickets in OPS, with no update for 10 days')

    await card(page).getByRole('button', { name: 'Every weekday', exact: true }).click()
    await card(page).getByRole('button', { name: 'Another time', exact: true }).click()
    await card(page).getByLabel('Time, Singapore').fill('15:00')
    await expect(card(page), 'the When part follows the schedule').toContainText('Every weekday at 15:00, Singapore time')
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
    await expect(card(page)).toContainText('bug tickets in OPS, with no update for 10 days')
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

  /** A follow-up the mock model reads whole, so the parts around it are what each test is about. */
  const STALE = 'find bug tickets in MOCK with no update for 10 days and create one ticket that lists them'
  const newestCard = (page: Page) => card(page).last()
  const partsOf = (page: Page) => newestCard(page).getByRole('list', { name: 'Each part of your request' })
  const whenPart = (page: Page) => partsOf(page).locator('[data-part="when"]')
  const crosses = (page: Page) => partsOf(page).locator('[data-mark="no"]')
  const partCan = (page: Page) => newestCard(page).getByRole('button', { name: 'Set up the part I can', exact: true })
  const turnedOn = (page: Page) => thread(page).getByRole('status').filter({ hasText: /is on\./ })

  async function leftOutOf(page: Page, backend: Backend): Promise<{ left_out: string[]; schedule: { day: string; at: string } | null }> {
    await turnedOn(page).getByRole('link', { name: 'See it on Workflows' }).click()
    await expect(page).toHaveURL(/\/workflows\/uc_/)
    const id = decodeURIComponent(new URL(page.url()).pathname.split('/').pop() ?? '')
    return backend.get(`alice`, `/api/v1/use-cases/${id}`)
  }

  test('ANS-cross and ANS-left-out: a clause the Planner didn’t follow is crossed, the button sets up the part it can, and the workflow keeps it as Left out', async ({ browser, backend }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, `Every Friday at 5pm, ${STALE}. Colour them by team.`)
    await expect(thread(page).getByText('Here’s what I understood. I can’t do every part of it.')).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can’t do yet' }), 'a clause it didn’t follow is no can’t').toHaveCount(0)
    await expect(crosses(page)).toHaveText(/Can’t do: “Colour them by team”\s*I didn’t follow this part\./)
    await expect(whenPart(page)).toContainText('Every Friday at 17:00, Singapore time')
    await expect(partCan(page)).toBeVisible()
    await fillTheRest(page, 'MOCK')
    await expect(left(page).last(), 'the footer says what is left out').toHaveText('The part with a cross is left out.', { timeout: 30_000 })
    await expect(newestCard(page), 'never Nothing is unclear while a part has a cross').not.toContainText('Nothing is unclear')
    await shot(page, info, 'r5-cross')
    await partCan(page).click()
    await expect(turnedOn(page)).toContainText('Left out: “Colour them by team”.', { timeout: 30_000 })
    const made = await leftOutOf(page, backend)
    expect(made.left_out, 'the workflow keeps her words for the part with a cross').toEqual(['Colour them by team'])
    await expect(main(page)).toContainText('Left out: “Colour them by team”. It was set up without that part.')
    await shot(page, info, 'r5-left-out-page')
    assertClean(watch)
    await context.close()
  })

  test('ANS-clash-day and FIX-day-choice: two days ask which one, never the first, and the workflow keeps her day and names only the other as left out', async ({ browser, backend }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, `Every Monday and Friday at 9am, ${STALE}`)
    await expect(whenPart(page)).toHaveAttribute('data-mark', 'ask')
    await expect(whenPart(page)).toContainText('Monday or Friday?')
    await expect(crosses(page)).toHaveText(/“Monday and Friday”\s*I can only set one day\./)
    await shot(page, info, 'r5-clash')
    await newestCard(page).getByRole('button', { name: 'Monday', exact: true }).click()
    await expect(whenPart(page)).toContainText('Every Monday at 9:00, Singapore time')
    await expect(crosses(page)).toHaveText(/“Friday”\s*I can only set one day, so it runs on Monday only\./)
    await fillTheRest(page, 'MOCK')
    await expect(left(page).last()).toHaveText('The part with a cross is left out.', { timeout: 30_000 })
    await partCan(page).click()
    await expect(turnedOn(page)).toContainText('Left out: “Friday”.', { timeout: 30_000 })
    const made = await leftOutOf(page, backend)
    expect(made.left_out).toEqual(['Friday'])
    expect(made.schedule).toMatchObject({ day: 'monday', at: '09:00' })
    assertClean(watch)
    await context.close()
  })

  test('ANS-clash-time, ANS-one-question and ANS-no-time: one question at a time, in order, and a time is never picked for her', async ({ browser, backend }, info) => {
    const before = await draftIds(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const asks = () => partsOf(page).locator('[data-mark="ask"]')
    await page.goto('/')
    await ask(page, `Every Friday at 9am and 5pm, ${STALE}`)
    await expect(whenPart(page)).toContainText('9:00 or 17:00?')
    await expect(partsOf(page), 'no time is ticked').not.toContainText('Singapore time')
    await newestCard(page).getByRole('button', { name: '17:00', exact: true }).click()
    await expect(whenPart(page)).toContainText('Every Friday at 17:00, Singapore time')

    await ask(page, SUMMARY)
    await expect(asks()).toHaveCount(1)
    await expect(whenPart(page)).toContainText('How often should it run?')
    await newestCard(page).getByRole('button', { name: 'Every week', exact: true }).click()
    await expect(asks()).toHaveCount(1)
    await expect(whenPart(page)).toContainText('Which day should it run?')
    await expect(newestCard(page).getByRole('button', { name: 'Monday', exact: true }), 'focus moves to the next question').toBeFocused()
    await newestCard(page).getByRole('button', { name: 'Friday', exact: true }).click()
    await expect(whenPart(page)).toContainText('What time should it run?')
    await shot(page, info, 'r5-question')
    await newestCard(page).getByRole('button', { name: '9:00', exact: true }).click()
    await expect(whenPart(page)).toContainText('Every Friday at 9:00, Singapore time')

    await ask(page, `Every Friday at 9, ${STALE}`)
    await expect(whenPart(page), 'a bare hour asks morning or evening').toContainText('At 9:00 or 21:00?')
    await expect(left(page).last()).toContainText('when it runs')
    assertClean(watch)
    await context.close()
    await forgetNewDrafts(backend, before)
  })

  test('ANS-whole-clause and the leftovers of other answers: what an answer didn’t read is marked above its card', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const newest = () => thread(page).locator(':scope > li').last()
    await page.goto('/')
    await ask(page, 'watch Kubernetes but only the major releases')
    await expect(newest().getByRole('list', { name: 'Each part of your request' })).toHaveText(/Can’t do: “only the major releases”\s*I didn’t follow this part\./)
    await ask(page, 'How are my workflows doing, and every Friday sum up the closed tickets')
    await expect(newest().getByRole('list', { name: 'Each part of your request' })).toHaveText(/“every Friday sum up the closed tickets”\s*Ask this on its own, and I’ll answer it\./)
    await expect(newest().getByRole('list', { name: 'Your workflows' }).first(), 'the question is still answered').toBeVisible()
    await shot(page, info, 'r5-leftovers')
    assertClean(watch)
    await context.close()
  })

  test('a new answer comes into view, from its top when it is taller than the conversation', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const inView = (answer: Locator) =>
      answer.evaluate((item) => {
        const region = item.closest('[role="region"]')!.getBoundingClientRect()
        const box = item.getBoundingClientRect()
        const top = box.top >= region.top - 1
        return box.height > region.height ? top && box.top <= region.top + 1 : top && box.bottom <= region.bottom + 1
      })
    await page.goto('/')
    // Enough answers first that a new one would land below the fold if the conversation didn't follow it.
    for (const text of ['What can you do?', 'What needs me?', 'What can you do?']) {
      const answer = await askAndWait(page, text)
      await expect.poll(() => inView(answer), { message: `the answer to “${text}” is in view` }).toBe(true)
    }
    const tall = await askAndWait(page, 'watch Kubernetes but only the major releases')
    await expect.poll(() => inView(tall), { message: 'the watch card is in view' }).toBe(true)
    await shot(page, info, 'answer-in-view')
    assertClean(watch)
    await context.close()
  })

  test('FIX-never-mind: the add-software card has Never mind, which changes nothing', async ({ browser, backend }) => {
    await backend.freshWatchlist('alice', [])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, 'Monitor Redis releases')
    await expect(thread(page).getByRole('button', { name: 'Add Redis' })).toBeVisible()
    await thread(page).getByRole('button', { name: 'Never mind' }).click()
    await expect(thread(page)).toContainText('Not added. Nothing changed.')
    const { watchlist } = await backend.get<{ watchlist: { software: { name: string }[] } | null }>('alice', '/api/v1/watchlist')
    expect(watchlist?.software.map((entry) => entry.name) ?? []).not.toContain('Redis')
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
    const row = page.locator('li[data-status]').filter({ hasText: 'Redis' })
    await expect(row, 'the row says it is not checked yet, and what checks it').toContainText(/Redis\s*Checked on GitHub · redis\/redis[\s\S]*Not checked yet/)
    await expect(page.locator('main h1 + p'), 'the count line counts it').toHaveText('1 not checked yet')
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

  test('the sketch’s three chips stay under the box in the chat, and Check my workflows, typed, draws the Workflows list’s own rows', async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [REDIS])
    await backend.waitingRun('alice')
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(ALICE_HEADING)
    const chips = page.getByRole('group', { name: 'Suggestions' }).getByRole('button')
    await expect(chips).toHaveCount(3)
    await expect(chips).toHaveText(['What needs me?', 'Which software is behind?', 'What can you do?'])
    const needsYou = main(page).getByRole('list', { name: 'Needs you' })
    await expect(needsYou.locator('li[data-home-item]').first(), 'Needs you is plain rows under the chips').toBeVisible()
    const total = await platformNeeds(backend, 'alice')

    await ask(page, 'Check my workflows')
    await expect(thread(page).getByRole('list', { name: 'Your workflows' })).toBeVisible()
    await expect(thread(page)).toContainText(/You have \d+ workflows?\./)
    await expect(needsYou, 'the rows give way to the strip while the thread shows').toHaveCount(0)
    await expect(chips, 'the chips stay under the box').toHaveText(['What needs me?', 'Which software is behind?', 'What can you do?'])
    await shot(page, info, 'n10-08-check')

    await chips.filter({ hasText: 'What needs me?' }).click()
    await expect(thread(page)).toContainText(`${total} ${total === 1 ? 'thing needs' : 'things need'} you.`)
    await page.getByRole('button', { name: 'New chat' }).click()
    await expect(thread(page)).toHaveCount(0)
    await expect(needsYou.locator('li[data-home-item]').first()).toBeVisible()
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

  test('the chip Which software is behind? is answered from the watchlist, with its Looked at line', async ({ browser, backend }) => {
    await backend.freshWatchlist('alice', [REDIS])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await page.getByRole('group', { name: 'Suggestions' }).getByRole('button', { name: 'Which software is behind?' }).click()
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
      await expect(page.locator('#side-panel-h'), 'Redis opens in the side panel').toHaveText('Redis')
      await page.locator('#side-panel').getByRole('link', { name: 'More details' }).click()
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
    for (const name of ['Ask, or describe a task', 'Send', 'Which software is behind?']) {
      expect(labels.some((label) => label.includes(name)), `Tab reaches ${name}; stops: ${labels.join(', ')}`).toBe(true)
    }
    expect(walk.unreached, 'controls Tab never reached').toEqual([])
    expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing').toEqual([])

    await tabTo(page, page.getByRole('button', { name: 'Which software is behind?' }))
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
    test(`Home and its answers pass WCAG 2.2 AA, do not scroll sideways and keep 24 px targets (WCAG 2.5.8) at ${size} px`, async ({ browser, backend }, info) => {
      await backend.waitingRun('alice')
      const before = await draftIds(backend)
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      await page.goto('/')
      await expect(box(page)).toBeVisible()
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `planner-home-${size}`)
      await noSideways(page)
      expect(await tooSmall(main(page).locator('button, a[href]')), 'WCAG 2.5.8: targets of at least 24 px, as the sketch’s 36 px chips are').toEqual([])
      await shot(page, info, `n10-08-home-${size}`)

      for (const [text, shown] of [
        ['Check my workflows', thread(page).getByRole('list', { name: 'Your workflows' })],
        ['What can you do?', thread(page).getByRole('heading', { name: 'I can', exact: true })],
        ['Every Friday, email me the list of tickets we closed this week', thread(page).getByRole('heading', { name: 'What I can’t do yet' })],
        [`Every Monday and Friday at 9am, ${STALE}. Colour them by team.`, thread(page).getByRole('list', { name: 'Each part of your request' }).locator('[data-mark="no"]')],
      ] as const) {
        await ask(page, text)
        await expect(shown.first()).toBeVisible()
      }
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `planner-thread-${size}`)
      await noSideways(page)
      await shot(page, info, `n10-08-thread-${size}`)
      await context.close()
      await forgetNewDrafts(backend, before)
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
      await expect(page.getByLabel('Ask, or describe a task')).toBeVisible()
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

  const pinned = (page: Page) => page.getByRole('region', { name: 'Needs you', exact: true })
  const pinnedOpen = (page: Page) => pinned(page).getByRole('link', { name: /^Open/ }).or(pinned(page).getByRole('button', { name: /^Open/ }))

  test('SHELL-pinned: the needs strip appears with the first message, the box docks with its chips, and N more plus one is the count everywhere', async ({ browser, backend }, info) => {
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
    await expect(box(page)).toHaveAttribute('placeholder', 'Ask, or describe a task')
    await expect(box(page), 'an answer with no card hands focus back to the box').toBeFocused()
    await expect(main(page).getByRole('list', { name: 'Needs you' }), 'Home’s rows give way to the strip').toHaveCount(0)
    await expect(page.getByRole('group', { name: 'Suggestions' }).getByRole('button'), 'the chips stay under the docked box').toHaveCount(3)
    const total = await platformNeeds(backend, 'alice')
    expect(total, 'a reply from the team and Jira not answering are two needs').toBeGreaterThan(1)
    await expect(pinnedOpen(page), 'Open shows a stop or a request in the side panel, and anything else on its page').toBeVisible()
    if ((await pinned(page).getByRole('link', { name: /^Open/ }).count()) > 0) await expect(pinned(page).getByRole('link', { name: /^Open/ })).toHaveAttribute('href', /^\/(settings|software|workflows)/)
    else await expect(pinned(page).getByRole('button', { name: /^Open/ })).toHaveAttribute('data-opens', /^run:/)
    await expect(pinned(page).getByRole('link', { name: `${String(total - 1)} more that need you` })).toHaveAttribute('href', '/workflows')
    await pinned(page).getByRole('link', { name: /more that need you/ }).click()
    await expect(page).toHaveURL(/\/workflows$/)
    await expect(main(page).getByRole('heading', { level: 2, name: new RegExp(`^Needs you ${String(total)}`) })).toBeVisible()
    await expect(main(page).getByRole('heading', { name: 'Do now' })).toBeVisible()
    await page.getByRole('link', { name: 'Back to the chat', exact: true }).click()
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

  test('ASK-needs: the answer counts what needs her, with one row each, and agrees with the platform', async ({ browser, backend }) => {
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await ask(page, 'What needs me?')
    const total = await platformNeeds(backend, 'alice')
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
    await expect(main(page).getByText(/^Good (morning|afternoon|evening), Bob$/)).toBeVisible()
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
    await expect(page.getByRole('link', { name: 'Back to the chat', exact: true })).toBeVisible()
    await expect(main(page).getByRole('link', { name: 'Workflows', exact: true }), 'the page’s own Back gives way to Back to the chat').toHaveCount(0)
    await page.getByRole('link', { name: 'Back to the chat', exact: true }).click()
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
    await expect(main(page).getByText(/^Good (morning|afternoon|evening), Bob$/)).toBeVisible()
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

  test('New chat clears the thread and brings back Home’s rows in place of the strip, and the keyboard reaches the box, New chat and the strip', async ({ browser, backend }) => {
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
    await expect(main(page).getByRole('list', { name: 'Needs you' })).toBeVisible()
    await expect(box(page)).toBeFocused()
    await repair()
    await context.close()
  })
})

test.describe('the edit card (spec 6.7)', () => {
  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  const WEEKDAYS_8 = { day: 'weekdays', at: '08:00' }
  const sentenceOf = (answer: Locator) => answer.locator('p[id$="-sentence"]')
  const heading = (answer: Locator) => editCard(answer).getByRole('heading', { level: 3 })

  test('ANS-edit-save: Save change publishes a version from the chat, the page lists it, and Undo publishes the one before again', async ({ browser, backend }) => {
    const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, WEEKDAYS_8)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    const answer = await askAndWait(page, `Make the ${morning.name} run on Mondays only`)
    await expect(sentenceOf(answer)).toHaveText('Here’s the change. Nothing changes until you save it.')
    await expect(heading(answer), 'the card takes focus on its heading').toBeFocused()
    await expect(heading(answer)).toHaveText(`Change ${morning.name}`)
    await expect(editCard(answer)).toHaveText(/When it runs\s*Before\s*Every weekday at 8:00\s*After\s*Every Monday at 8:00/)
    await expect(answer.getByRole('button', { name: 'Turn it on' }), 'no new set-up card').toHaveCount(0)
    expect((await versionsOf(backend, morning.id)).map((v) => v.version), 'nothing is saved before Save change').toEqual([2, 1])

    await editCard(answer).getByRole('button', { name: 'Save change' }).click()
    await expect(editCard(answer)).toContainText(/Saved as version 3\. Next run .+, 8:00\./)
    await expect(sentenceOf(answer)).toHaveText(`Saved. ${morning.name} runs every Monday at 8:00 now.`)
    await expect(editCard(answer).getByRole('button', { name: /^Undo/ })).toBeFocused()
    expect(await shown(backend, morning.id)).toMatchObject({ version: 3, schedule: { day: 'monday', at: '08:00' } })
    expect((await versionsOf(backend, morning.id))[0]).toMatchObject({ version: 3, by: 'alice', via: 'chat' })

    const rail = page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })
    await rail.getByRole('link', { name: /^Workflows/ }).click()
    await main(page).getByRole('link', { name: morning.name, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/workflows/${morning.id}$`))
    await expect(page.getByRole('list', { name: 'Versions, newest first' }).getByRole('listitem').first()).toContainText('Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00. This is the version running now.')
    await rail.getByRole('link', { name: /^Chat/ }).click()
    const kept = newestAnswer(page)
    await expect(editCard(kept), 'the card keeps its Undo across pages').toContainText('Saved as version 3.')
    await editCard(kept).getByRole('button', { name: /^Undo/ }).click()
    await expect(sentenceOf(kept)).toHaveText(`Undone, as version 4. ${morning.name} runs every weekday at 8:00 now.`)
    await expect(editCard(kept)).toContainText('Undone, as version 4.')
    expect(await shown(backend, morning.id)).toMatchObject({ version: 4, schedule: WEEKDAYS_8 })
    expect((await versionsOf(backend, morning.id))[0]).toMatchObject({ version: 4, via: 'chat', undid: 3 })
    await expectAccessible(page, path.join(OUT, 'axe'), 'r8-edit-card')
    assertClean(watch)
    await context.close()
  })

  test('ANS-edit-after: a later change on its page is named and takes Undo away, a stale Undo is refused with a 409, and a paused workflow says so', async ({ browser, backend }) => {
    const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, WEEKDAYS_8)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    const answer = await askAndWait(page, `Make the ${morning.name} run on Mondays only`)
    const reread = rereadOf(page, morning.id)
    await editCard(answer).getByRole('button', { name: 'Save change' }).click()
    await expect(editCard(answer)).toContainText('Saved as version 3.')
    await reread
    const later = await backend.send('PUT', 'carol', `/api/v1/use-cases/${morning.id}/schedule`, { day: 'friday', at: '17:30' })
    expect(later.status, 'carol changes it on its page').toBe(200)
    await editCard(answer).getByRole('button', { name: /^Undo/ }).click()
    await expect(editCard(answer).getByRole('alert')).toHaveText(`Could not undo version 3. ${morning.name} changed again since, so Undo would throw that change away.`)
    await expect(editCard(answer)).toContainText('Saved as version 3. Changed again since, on its page.')
    await expect(editCard(answer).getByRole('button', { name: /^Undo/ }), 'no Undo that would throw away a later change').toHaveCount(0)
    expect(await shown(backend, morning.id), 'the stale Undo published nothing').toMatchObject({ version: 4, schedule: { day: 'friday', at: '17:30' } })

    await backend.post('alice', `/api/v1/use-cases/${morning.id}/pause`)
    const paused = await askAndWait(page, `Make the ${morning.name} run at 9am`)
    await editCard(paused).getByRole('button', { name: 'Save change' }).click()
    await expect(sentenceOf(paused)).toHaveText(`Saved. ${morning.name} is paused, so it won’t run until you resume it.`)
    await expect(editCard(paused)).toContainText('Saved as version 5. It’s paused, so it won’t run until you resume it.')
    await context.close()
  })

  test('ANS-asks, ANS-edit-days and ANS-edit-honest: a bare hour is asked, two days hold Save, “it” is the workflow just discussed, and a change it can’t make names the workflow', async ({ browser, backend }) => {
    const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, WEEKDAYS_8)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')

    const hour = await askAndWait(page, `make the ${morning.name} run at 9`)
    await expect(editCard(hour)).toContainText('At 9:00 or 21:00?')
    await expect(editCard(hour)).toHaveText(/After\s*Choose a time/)
    await editCard(hour).getByRole('button', { name: '9:00', exact: true }).click()
    await expect(editCard(hour)).toHaveText(/After\s*Every weekday at 9:00/)
    await expect(editCard(hour).getByRole('button', { name: 'Save change' }), 'focus moves to Save change once the time is picked').toBeFocused()

    const it = await askAndWait(page, 'make it daily')
    await expect(heading(it), '“it” is the workflow the answer before was about').toHaveText(`Change ${morning.name}`)
    await expect(editCard(it)).toHaveText(/Before\s*Every weekday at 8:00\s*After\s*Every day at 8:00/)

    const days = await askAndWait(page, `make the ${morning.name} run on Mondays and Thursdays`)
    await expect(editCard(days)).toHaveText(/“Mondays and Thursdays”\s*I can only set one day\./)
    await expect(editCard(days)).toContainText('Ask again without the part with a cross.')
    await expect(editCard(days).getByRole('button', { name: 'Save change' }), 'no Save change that can’t work').toHaveCount(0)

    const rename = await askAndWait(page, `rename the ${morning.name} to Daily tickets`)
    await expect(sentenceOf(rename)).toHaveText(`From the chat I can only change when ${morning.name} runs.`)
    await expect(editCard(rename)).toHaveCount(0)
    await expect(rename.getByRole('button', { name: `Open ${morning.name}` }).or(rename.getByRole('link', { name: `Open ${morning.name}` }))).toBeVisible()

    const react = await askAndWait(page, 'Make the React check run on Mondays only')
    await expect(sentenceOf(react)).toHaveText(/^You don’t have a React check\. React isn’t on the Software watchlist/)
    await expect(react.getByRole('button', { name: 'Watch React' })).toBeVisible()
    const missing = await askAndWait(page, `make the purple ${tag()} report run on Mondays only`)
    await expect(sentenceOf(missing)).toHaveText(/^You don’t have a workflow called “purple \w+ report”\.$/)
    expect(await shown(backend, morning.id), 'no answer saved anything').toMatchObject({ version: 2, schedule: WEEKDAYS_8 })
    await context.close()
  })

  test('ANS-status-commands, ANS-questions, ANS-name-words and FIX-name-*: a change beside a question is a command, a question is never one, and a schedule word in a name is neither', async ({ browser, backend }) => {
    const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, WEEKDAYS_8)
    const weekly = await scheduledWorkflow(backend, `Weekly report ${tag()}`, { day: 'friday', at: '16:00' })
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')

    const pause = await askAndWait(page, `what needs my attention? pause the ${morning.name}`)
    await expect(sentenceOf(pause)).toHaveText(`From the chat I can only change when ${morning.name} runs.`)
    await expect(pause).toHaveText(/“what needs my attention”\s*Ask this on its own, and I’ll answer it\./)
    const both = await askAndWait(page, `how are my workflows doing? make the ${morning.name} run at 10am`)
    await expect(editCard(both)).toHaveText(/Before\s*Every weekday at 8:00\s*After\s*Every weekday at 10:00/)

    const next = await askAndWait(page, `when does the ${morning.name} run next?`)
    await expect(editCard(next), 'a question is never a change').toHaveCount(0)
    await expect(next).not.toContainText('I can only change')
    const asked = await askAndWait(page, `when does the ${morning.name} run? make it run daily`)
    await expect(editCard(asked)).toHaveText(/Before\s*Every weekday at 8:00\s*After\s*Every day at 8:00/)

    const ten = await askAndWait(page, `make the ${weekly.name} run at 10am`)
    await expect(editCard(ten), 'only the time changes, and the day stays').toHaveText(/Before\s*Every Friday at 16:00\s*After\s*Every Friday at 10:00/)
    const how = await askAndWait(page, `how is the ${weekly.name} doing?`)
    await expect(editCard(how), 'FIX-name-not-command: a name with “weekly” in it asks nothing').toHaveCount(0)
    await expect(how.getByRole('button', { name: 'Turn it on' })).toHaveCount(0)
    await context.close()
  })

  test('ANS-edit-never and the watchlist: Never mind changes nothing, and saving the watchlist’s schedule says who owns it, with no Undo it can’t keep', async ({ browser, backend }, info) => {
    const before = (await backend.get<{ watchlist: { schedule: { day: string; at: string } | null } | null }>('alice', '/api/v1/watchlist')).watchlist?.schedule ?? null
    if ((await backend.get<{ watchlist: unknown }>('alice', '/api/v1/watchlist')).watchlist === null) await backend.freshWatchlist('alice')
    const put = await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
    expect(put.status).toBe(200)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    try {
      await page.goto('/')
      const never = await askAndWait(page, 'Run the software check every day instead of every Monday')
      await expect(editCard(never)).toHaveText(/Before\s*Every Monday at 9:00\s*After\s*Every day at 9:00[\s\S]*software on the watchlist are checked\. Saving makes you the owner of this schedule\./)
      await editCard(never).getByRole('button', { name: 'Never mind' }).click()
      await expect(sentenceOf(never)).toHaveText('No problem. Nothing changed.')
      await expect(box(page), 'Never mind hands focus back to the box').toBeFocused()
      await expect(editCard(never)).toHaveCount(0)
      expect((await backend.get<{ watchlist: { schedule: { day: string } } }>('alice', '/api/v1/watchlist')).watchlist.schedule.day, 'Never mind changed nothing').toBe('monday')

      const seven = await askAndWait(page, 'Run the software check every day at 7am')
      await editCard(seven).getByRole('button', { name: 'Save change' }).click()
      await expect(sentenceOf(seven)).toHaveText(/^Saved\. Next run .+, 7:00\. You now own this schedule, so you can’t approve its checks\.$/)
      await expect(editCard(seven)).toContainText('and made you the owner of this schedule.')
      await expect(editCard(seven).getByRole('button', { name: /^Undo/ })).toHaveCount(0)
      await expect(editCard(seven).getByRole('link', { name: 'Change it on the Software page' })).toBeVisible()
      for (const width of [1920, 1280, 900, 390]) {
        await page.setViewportSize({ width, height: 900 })
        await noSideways(page)
        await shot(page, info, `r8-edit-watchlist-saved-${String(width)}`)
      }
    } finally {
      if (before) await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', before)
      else await backend.send('DELETE', 'alice', '/api/v1/watchlist/schedule')
      await context.close()
    }
  })

  test('choices: words that fit two workflows ask which, and picking one shows its change', async ({ browser, backend }) => {
    const both = tag()
    await scheduledWorkflow(backend, `Friday digest ${both}`, { day: 'friday', at: '16:00' })
    await scheduledWorkflow(backend, `Friday follow-up ${both}`, WEEKDAYS_8)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    const which = await askAndWait(page, `make the Friday ${both} one run at 10am`)
    await expect(sentenceOf(which)).toHaveText('Which workflow should I change?')
    await expect(heading(which)).toBeFocused()
    await editCard(which).getByRole('button', { name: `Friday follow-up ${both}` }).click()
    await expect(heading(which)).toHaveText(`Change Friday follow-up ${both}`)
    await expect(editCard(which)).toHaveText(/Before\s*Every weekday at 8:00\s*After\s*Every weekday at 10:00/)
    await context.close()
  })

  test('pressing on the card: Save waits for the workflow’s read, Enter in Another time only picks, and saving one card turns an older card on the same workflow stale', async ({ browser, backend }) => {
    const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, WEEKDAYS_8)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const puts: string[] = []
    page.on('request', (request) => {
      if (request.method() === 'PUT' && request.url().includes(morning.id)) puts.push(request.url())
    })
    let release: () => void = () => undefined
    const held = new Promise<void>((resolve) => (release = resolve))
    await page.route(`**/api/v1/use-cases/${morning.id}`, async (route) => {
      if (route.request().method() === 'GET') await held
      await route.continue()
    })
    await page.goto('/')

    const early = await askAndWait(page, `make the ${morning.name} run at 10am`)
    const save = editCard(early).getByRole('button', { name: 'Save change' })
    await expect(save, 'Save waits while the workflow is read').toHaveAttribute('aria-busy', 'true')
    await save.click({ force: true })
    release()
    await expect(save).not.toHaveAttribute('aria-busy', 'true')
    expect(puts, 'a press before the read saved nothing').toEqual([])

    const unread = await askAndWait(page, `make the ${morning.name} run on Mondays in the afternoon`)
    await expect(editCard(unread)).toContainText('What time should it run?')
    await editCard(unread).getByRole('button', { name: 'Another time' }).click()
    await editCard(unread).getByLabel('Time, Singapore').fill('10:05')
    await editCard(unread).getByLabel('Time, Singapore').press('Enter')
    await expect(editCard(unread)).toHaveText(/After\s*Every Monday at 10:05/)
    expect(puts, 'Enter in Another time picks the time and saves nothing').toEqual([])

    await editCard(unread).getByRole('button', { name: 'Save change' }).click()
    await expect(editCard(unread)).toContainText('Saved as version 3.')
    await expect(early.locator('p[id$="-sentence"]'), 'the older card on the same workflow is out of date now').toHaveText(`${morning.name} changed since I read it, and runs every Monday at 10:05 now. Ask again to change it.`)
    await expect(editCard(early), 'and offers no Save').toHaveCount(0)
    expect(await shown(backend, morning.id)).toMatchObject({ version: 3, schedule: { day: 'monday', at: '10:05' } })
    await context.close()
  })

  test('bob, an Approver, never gets an edit answer', async ({ backend }) => {
    const morning = await scheduledWorkflow(backend, `Morning check ${tag()}`, WEEKDAYS_8)
    const answer = await backend.send<{ answer?: string }>('POST', 'bob', '/api/v1/planner/answer', { text: `Make the ${morning.name} run on Mondays only` })
    expect([answer.status, answer.body.answer], 'bob is told who makes changes, never given an edit').toEqual([200, 'operators'])
    expect(await shown(backend, morning.id)).toMatchObject({ version: 2, schedule: WEEKDAYS_8 })
  })
})

/**
 * Bob, an Approver who isn't an Operator, asks questions only (ADR 0043, spec 5.3). Matches ROLE-home, ROLE-asks, ROLE-refuse,
 * ROLE-panel, KEYS-ROLE, FIX-decided-whole, FIX-approve-any-object, FIX-decisions-detail and FOLLOW-bob-mixed in checks/paths-v4.cjs.
 */
test.describe('bob asks the Planner questions only', () => {
  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  const bobBox = (page: Page) => page.getByLabel('Ask, or describe a task')
  const newest = (page: Page) => thread(page).locator(':scope > li').last()
  const said = (page: Page) => newest(page).locator('p').first()
  const panel = (page: Page) => page.locator('#side-panel')
  const OPS = /^Operators set up workflows\. Ask .+\.$/
  const CHANGES = [/^Turn it on$/, /^Save/, /^Pause/, /^Resume/, /^Retry/, /^Run now$/, /^Check now$/, /^Add .*watchlist/i, /^Set it up with a yes$/, /^Approve/, /^Decline/]

  async function bobAsks(page: Page, text: string): Promise<void> {
    const before = await thread(page).locator(':scope > li[data-answer]').count()
    await bobBox(page).fill(text)
    await bobBox(page).press('Enter')
    await expect(thread(page).locator(':scope > li[data-answer]')).toHaveCount(before + 1)
    await expect(newest(page)).toHaveAttribute('data-answer', 'true')
  }

  async function noChangeControl(page: Page): Promise<void> {
    for (const name of CHANGES) await expect(thread(page).getByRole('button', { name }), `no ${String(name)} in any answer`).toHaveCount(0)
    await expect(thread(page).locator('section[data-card]'), 'no set-up or edit card').toHaveCount(0)
  }

  /** A run Alice started that Bob declined, so he has a decision of his own to ask about. */
  async function bobDeclined(backend: Backend, reason: string): Promise<void> {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
    await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'decline', digest, reason }, undefined, [201])
    await backend.waitForState(runId, ['rejected'])
  }

  test('ROLE-home and ROLE-asks: bob’s Home has the box and his three questions above Needs you, and each answer comes from platform state', async ({ browser, backend }, info) => {
    await bobDeclined(backend, 'Wrong version')
    await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(main(page).getByText(/^Good (morning|afternoon|evening), Bob$/)).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 }), 'his heading says what waits for his yes').toHaveText(/^(\d+ requests? (is|are) waiting for your yes|\d+ things? needs? you)\.$/)
    const line = (await page.getByRole('heading', { level: 1 }).innerText()).trim()
    await expect(bobBox(page)).toHaveAttribute('placeholder', 'Ask, or describe a task')
    const chips = page.getByRole('group', { name: 'Suggestions' }).getByRole('button')
    await expect(chips).toHaveText(['What is waiting for my yes?', 'What did I decide before?', 'How are the workflows doing?'])
    const tops = await Promise.all([bobBox(page), chips.first(), main(page).getByRole('list', { name: 'Needs you' })].map(async (at) => (await at.boundingBox())?.y ?? -1))
    expect(tops.every((top, index) => top >= 0 && (index === 0 || top > (tops[index - 1] ?? 0))), 'box, then the questions, then Needs you').toBe(true)
    await expect(main(page)).toContainText('You’re an Approver, so you decide on requests. Operators set up workflows.')
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), 'planner-home-bob')
    await shot(page, info, 'r16-bob-home')

    await chips.first().click()
    await expect(said(page), 'what waits for his yes is his Home heading').toHaveText(line)
    await expect(newest(page).getByRole('button', { name: 'Review and decide' }).first()).toBeVisible()
    await bobAsks(page, 'What did I decide before?')
    await expect(said(page)).toHaveText(/^Here (is your decision|are your \d+ decisions)\./)
    await expect(newest(page).getByRole('list', { name: 'Your decisions' })).toContainText(/Declined\s*Declined by Bob at \d+:\d\d today\. Nothing was written\. Reason: Wrong version\./)
    await bobAsks(page, 'did I decline anything?')
    await expect(said(page)).toHaveText(/^You declined \d+ requests?\./)
    const verdicts = await newest(page).locator('[data-verdict]').evaluateAll((pills) => pills.map((pill) => pill.getAttribute('data-verdict')))
    expect(verdicts.length > 0 && verdicts.every((verdict) => verdict === 'decline'), 'FIX-decisions-detail: only declines').toBe(true)
    await bobAsks(page, 'How are the workflows doing?')
    await expect(said(page)).toHaveText(/^The team has \d+ workflows?\./)
    await bobAsks(page, 'What can you do?')
    await expect(newest(page)).toContainText(/What you decided before, with when, and any reason you gave[\s\S]*Operators set up workflows\. Ask /)
    await noChangeControl(page)
    await shot(page, info, 'r16-bob-asks')
    assertClean(watch)
    await context.close()
  })

  test('ROLE-refuse and FIX-approve-any-object: every change gets who makes changes, an approve goes to the request, and nothing changes', async ({ browser, backend }, info) => {
    await backend.waitingRun('alice')
    const workflows = async () => (await backend.get<{ use_cases: { use_case_id: string; state: string }[] }>('alice', '/api/v1/use-cases')).use_cases
    const before = await workflows()
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    for (const change of ['Pause the weekly closed-ticket summary', 'Every Friday, sum up the tickets we closed this week', 'Watch Redis releases', 'Could you make the morning check daily?']) {
      await bobAsks(page, change)
      await expect(said(page), `“${change}” gets who makes changes`).toHaveText(OPS)
      await noChangeControl(page)
    }
    await shot(page, info, 'r16-bob-refused')
    // The reading may take an approve for a way around the gate and refuse it, and the refusal stands. Either way he gets the request to open.
    for (const decide of ['approve the upgrade tickets', 'decline that request', 'auto-approve everything', 'approve it for me']) {
      await bobAsks(page, decide)
      await expect(said(page)).toHaveText(/^(I can’t approve or decline for you\. Open the request to see exactly what it will write, and decide there\.|I can’t set that up\. Anything that changes data waits for a yes, every time\.)$/)
      await expect(newest(page).getByRole('button', { name: 'Review and decide' }).first()).toBeVisible()
    }
    await bobAsks(page, 'approve the upgrade and pause the morning new-ticket check')
    await expect(said(page), 'an approve beside a change is refused whole, by builder or by the reading').toHaveText(/^(Operators set up workflows\. Ask .+\.|I can’t set that up\. Anything that changes data waits for a yes, every time\.)$/)
    await noChangeControl(page)
    expect(await workflows(), 'nothing changed').toEqual(before)
    assertClean(watch)
    await context.close()
  })

  test('FOLLOW-bob-mixed: a question asked with a change is answered as it is alone, and the change has a cross saying who makes changes', async ({ browser, backend }, info) => {
    await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    await page.goto('/')
    await bobAsks(page, 'What is waiting for my yes?')
    const alone = (await said(page).innerText()).trim()
    await bobAsks(page, 'What is waiting for my yes, and pause the morning new-ticket check')
    await expect(said(page)).toHaveText(alone)
    await expect(newest(page).getByRole('list', { name: 'Each part of your request' })).toContainText(/“pause the morning new-ticket check”\s*Operators set up workflows\. Ask /)
    await noChangeControl(page)
    await shot(page, info, 'r16-bob-mixed')
    await context.close()
  })

  test('FIX-decided-whole: asking to see past decisions reads the whole question, with no part crossed', async ({ browser, backend }) => {
    await bobDeclined(backend, 'Not this week')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    await page.goto('/')
    await bobAsks(page, 'show my past decisions')
    await expect(said(page)).toHaveText(/^Here (is your decision|are your \d+ decisions)\./)
    await expect(newest(page).locator('[data-mark="no"]')).toHaveCount(0)
    await context.close()
  })

  test('ROLE-panel and KEYS-ROLE: by keyboard bob asks, opens the request from the answer in the side panel, approves there, and his card follows', async ({ browser, backend }, info) => {
    const { runId } = await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob', { reducedMotion: true })
    const page = await context.newPage()
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.goto('/')
    await page.locator('h1').focus()
    await tabTo(page, bobBox(page))
    await page.keyboard.type('What is waiting for my yes?')
    await page.keyboard.press('Enter')
    await expect(newest(page)).toHaveAttribute('data-answer', 'true')
    const opener = newest(page).locator(`[data-opens="run:${runId}"]`)
    await tabTo(page, opener)
    const ring = await opener.evaluate((el) => { const style = getComputedStyle(el); return (style.outlineStyle !== 'none' && style.outlineWidth !== '0px') || style.boxShadow !== 'none' })
    expect(ring, 'Review and decide shows its focus').toBe(true)
    await page.keyboard.press('Enter')
    await expect(page.locator('#side-panel-h'), 'focus goes to the panel’s heading').toBeFocused()
    await shot(page, info, 'r16-bob-panel')
    await panel(page).getByRole('button', { name: /^Approve/ }).click()
    await expect(panel(page).getByRole('button', { name: /^Approve/ }), 'the decision is made in the panel').toHaveCount(0, { timeout: 30_000 })
    await expect(panel(page), 'the panel shows the run done').toContainText(/Done\s*\d+ tickets? created in Jira/, { timeout: 30_000 })
    await panel(page).getByRole('button', { name: 'Close' }).click()
    await expect(newest(page).locator(`[data-opens="run:${runId}"]`), 'his card no longer offers the request').toHaveCount(0, { timeout: 20_000 })
    await context.close()
  })
})
