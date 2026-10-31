import AxeBuilder from '@axe-core/playwright'
import { expect, request, test, type Browser, type Page } from '@playwright/test'
import { randomBytes } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import {
  connectAndSave,
  everythingOnThePage,
  MOCK_MODEL,
  MOCK_MODEL_URL,
  openSettings,
  personRow,
  roleBox,
  settingsTab,
  SettingsApi,
  signedInAs,
  type Person,
} from '../live/support/settings'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p10'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const PERF_PEOPLE = 30

const ONLY_OPERATORS = 'Only Operators change settings.'
const NOT_SIGNED_IN = 'Hasn’t signed in yet'
const TWO_APPROVERS = 'At least 2 people must be Approvers, so nobody has to approve their own work.'
const SUMMARY_TASK = 'Every Friday summarise the tickets we finished in MOCK.'
const WIDE_PENDING = 'wide-pending@example.test'
// The same mock model under a second name (deploy/compose.e2e.yaml), so lane 2 can enter an address the platform has
// never confirmed while the first one is in use.
const SECOND_MODEL_URL = process.env['SECOND_MODEL_URL'] ?? 'http://mock-model-2:8300'
const MOCK_OIDC_URL = process.env['MOCK_OIDC_URL'] ?? 'http://mock-oidc:8080/default'
const LEFT = 'no longer on the list'
const RUN_SETTLED = ['awaiting_approval', 'succeeded', 'rejected', 'failed']

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = true): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })
const freshKey = (lane: string) => `p10-${lane}-${randomBytes(12).toString('hex')}`

async function withApi<T>(act: (api: SettingsApi) => Promise<T>): Promise<T> {
  const api = await SettingsApi.connect(BASE_URL)
  try {
    return await act(api)
  } finally {
    await api.dispose()
  }
}

async function runsNow(api: SettingsApi, lane: string) {
  const plan = await api.send<{ decision?: string }>('alice', 'POST', '/api/v1/builder/plan', { task: SUMMARY_TASK })
  const made = await api.send<{ use_case_id?: string }>('alice', 'POST', '/api/v1/agent-use-cases', {
    name: `${lane} model check`,
    instruction: 'Run the agent.',
    agents: [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'acme/planted', 'Jira project': 'MOCK' } }],
  })
  expect(made.status, `alice sets up an agent workflow: ${JSON.stringify(made.body)}`).toBe(201)
  const run = await api.send('alice', 'POST', `/api/v1/use-cases/${made.body.use_case_id ?? ''}/runs`, undefined, { 'Idempotency-Key': `${lane}-${Date.now()}` })
  return { plan, made, run }
}

/** Polls a run until it waits for a yes or ends, so a lane can say the run did its work with the model. */
async function runSettles(api: SettingsApi, runId: string): Promise<{ state: string; reason: string | null }> {
  let last = { state: 'unknown', reason: null as string | null }
  await expect
    .poll(
      async () => {
        const answer = await api.send<{ state?: string; reason?: string | null }>('alice', 'GET', `/api/v1/runs/${runId}`)
        last = { state: answer.body.state ?? `HTTP ${answer.status}`, reason: answer.body.reason ?? null }
        return RUN_SETTLED.includes(last.state)
      },
      { message: `run ${runId} waits for a yes or ends`, timeout: 120_000, intervals: [1_000] },
    )
    .toBe(true)
  return last
}

async function onlyAliceAndBobApprove(api: SettingsApi): Promise<void> {
  const approvers = (await api.people()).filter((p) => p.approver).map((p) => p.id)
  expect(approvers.sort(), 'this lane needs a stack where only alice and bob are Approvers').toEqual(['alice', 'bob'])
}

async function as(browser: Browser, user: string, phone = false) {
  const context = await signedInAs(browser, user, { phone })
  const page = await context.newPage()
  const watch = watchPage(page)
  return { context, page, watch }
}

test('@lane1-trunk trunk has no Settings tabs', async ({ browser }) => {
  const { context, page } = await as(browser, 'alice')
  await page.goto('/settings')
  await expect(h1(page)).toHaveText('Settings')
  const main = await page.getByRole('main').innerText()
  const tabs = await page.getByRole('group', { name: 'Settings sections' }).count()
  await shotTo(page, 1, 'p10-model-trunk.png')
  save(1, 'p10-trunk.json', { target: 'trunk', url: page.url(), tabs, main })
  expect(tabs, 'trunk has no Settings tabs').toBe(0)
  await context.close()
})

test('@lane1 alice connects the mock model, tests and saves it, and only the key’s last two characters show', async ({ browser }) => {
  await withApi(async (api) => {
    const key = freshKey('lane1')
    const { context, page, watch } = await as(browser, 'alice')
    await openSettings(page)
    await page.getByLabel('Provider').selectOption('other')
    await page.getByLabel('Address', { exact: true }).fill(MOCK_MODEL_URL)
    await page.getByLabel('API key').fill(key)
    await page.getByRole('button', { name: 'Connect', exact: true }).click()
    const models = page.getByLabel('Model', { exact: true })
    await expect(models).toBeVisible({ timeout: 30_000 })
    const offered = await models.locator('option').evaluateAll((options: HTMLOptionElement[]) => options.map((option) => ({ value: option.value, text: option.text.trim() })))
    await shotTo(page, 1, 'p10-model-list.png')
    await models.selectOption(MOCK_MODEL)
    await page.getByRole('button', { name: 'Test and save' }).click()
    await expect(page.getByRole('button', { name: 'Connect', exact: true })).toBeVisible({ timeout: 30_000 })
    const waiting = page.locator('#model-waiting')
    const waited = await waiting.isVisible()
    let own: { confirmButtons: number; modelTab: string; aliceDecides: number } | null = null
    if (waited) {
      const { pending } = await api.model('alice')
      own = {
        confirmButtons: await waiting.getByRole('button', { name: 'Confirm address' }).count(),
        modelTab: await settingsTab(page, 'AI model').innerText(),
        aliceDecides: (await api.send('alice', 'POST', '/api/v1/settings/model/address-decision', { verdict: 'confirm', digest: pending?.digest })).status,
      }
      await shotTo(page, 1, 'p10-own-address.png')
      await api.confirmAddress('bob')
    }
    await page.reload()
    await expect(page.locator('#model-now')).toContainText(`API key ending ${key.slice(-2)}`)
    await expect(page.locator('#model-now')).toContainText(MOCK_MODEL)
    await shotTo(page, 1, 'p10-model.png')
    const everything = await everythingOnThePage(page)
    const text = await page.getByRole('main').innerText()
    const model = await api.model('alice')
    save(1, 'p10-model.json', { offered, waitedForAnApprover: waited, own, active: model.active, keyEnding: key.slice(-2) })
    expect(offered.map((option) => option.value), `the model list offers ${MOCK_MODEL}`).toContain(MOCK_MODEL)
    expect(model.active?.base_url).toBe(MOCK_MODEL_URL)
    expect(model.active?.model).toBe(MOCK_MODEL)
    expect(model.active?.key_hint).toBe(key.slice(-2))
    expect(everything.includes(key.slice(0, -2)), 'more of the key than its last two characters is on the page').toBe(false)
    expect(text.includes(key.slice(-3)), 'more than the last two characters is in the page text').toBe(false)
    if (own) {
      expect(own.confirmButtons, 'alice entered the address, so she gets no Confirm address').toBe(0)
      expect(own.modelTab, 'the AI model tab does not say it needs alice while her own address waits').not.toContain('needs you')
      expect(own.aliceDecides, 'the platform refuses alice confirming her own address').toBe(403)
    }
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 with no model runs get 409; with a model in use, carol enters an address not on the known list, it waits for an Approver, and runs keep the model in use', async ({ browser }) => {
  test.setTimeout(300_000)
  await withApi(async (api) => {
    const fresh = await api.model('alice')
    expect(fresh.active, 'lane 2 needs a fresh stack, where no model was ever connected').toBeNull()
    const noModel = await runsNow(api, 'lane2-no-model')
    // alice connects the mock model and bob confirms its address, so runs have a model in use.
    const alice = await as(browser, 'alice')
    await openSettings(alice.page)
    await connectAndSave(alice.page, { key: freshKey('lane2-first') })
    await api.confirmAddress('bob')
    assertClean(alice.watch)
    await alice.context.close()
    const before = await api.model('alice')
    expect(before.active?.base_url, 'the first address is in use').toBe(MOCK_MODEL_URL)
    expect(before.pending, 'nothing waits before carol').toBeNull()

    const { context, page, watch } = await as(browser, 'carol')
    await openSettings(page)
    await connectAndSave(page, { address: SECOND_MODEL_URL, key: freshKey('lane2') })
    const waiting = page.locator('#model-waiting')
    await expect(waiting, 'the platform has never confirmed the second address, so it waits').toBeVisible()
    await expect(waiting).toContainText('A new address is waiting for an Approver')
    await expect(waiting).toContainText('Entered by Carol')
    await expect(waiting.getByRole('button', { name: 'Confirm address' })).toHaveCount(0)
    await expect(settingsTab(page, 'AI model'), 'carol entered it and cannot confirm it, so the tab does not say it needs her').not.toContainText('needs you')
    await expect(page.locator('#model-now'), 'the page still names the model in use').toContainText(MOCK_MODEL)
    await shotTo(page, 2, 'p10-pending-address.png')
    const after = await api.model('alice')
    const runs = await runsNow(api, 'lane2')
    const runId = (runs.run.body as { run_id?: string }).run_id ?? ''
    const served = runs.run.status === 201 ? await runSettles(api, runId) : null
    const still = await api.model('alice')
    save(2, 'p10-pending-address.json', { noModel, before: before.active, after: after.active, pending: after.pending, runs, served, afterTheRun: { active: still.active, pending: still.pending } })
    expect(noModel.plan.status, `with no model the Planner answers 409: ${JSON.stringify(noModel.plan.body)}`).toBe(409)
    expect(noModel.run.status, `with no model an agent run answers 409: ${JSON.stringify(noModel.run.body)}`).toBe(409)
    expect(JSON.stringify(noModel.run.body)).toContain('Connect an AI model in Settings to run agents.')
    expect(after.pending?.by).toBe('carol')
    expect(after.pending?.base_url).toBe(SECOND_MODEL_URL)
    expect(after.active, 'runs keep the model in use').toEqual(before.active)
    expect(runs.plan.status, `the Planner answers with the model in use: ${JSON.stringify(runs.plan.body)}`).toBe(200)
    expect(runs.plan.body.decision, 'the Planner made a decision').toBeTruthy()
    expect(runs.run.status, `an agent run starts with the model in use: ${JSON.stringify(runs.run.body)}`).toBe(201)
    expect(served?.state, `the run did its work with the model in use: ${JSON.stringify(served)}`).toMatch(/^(awaiting_approval|succeeded)$/)
    expect(still.active, 'the run left the model in use as it was').toEqual(before.active)
    expect(still.pending?.base_url, 'carol’s address still waits').toBe(SECOND_MODEL_URL)
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 bob confirms carol’s address, the Planner and agent runs use the new model, and the history names both', async ({ browser }) => {
  await withApi(async (api) => {
    expect((await api.model('bob')).pending?.by, 'run lane 2 on this stack first').toBe('carol')
    const { context, page, watch } = await as(browser, 'bob')
    await openSettings(page)
    await expect(settingsTab(page, 'AI model')).toContainText('needs you')
    await page.locator('#model-waiting').getByRole('button', { name: 'Confirm address' }).click()
    await expect(page.locator('#model-now')).toContainText(`Confirmed. Runs now use ${MOCK_MODEL}.`)
    await expect(page.locator('#model-now')).toBeFocused()
    await page.getByText(/^Change history/).click()
    await expect(page.locator('details')).toContainText('Asked by Carol, decided by Bob.')
    await shotTo(page, 3, 'p10-address-confirmed.png')
    const model = await api.model('alice')
    const history = await api.history('alice')
    const runs = await runsNow(api, 'lane3')
    save(3, 'p10-address-confirmed.json', { active: model.active, pending: model.pending, history: history.filter((line) => line.area === 'model'), runs })
    expect(model.active?.base_url, 'carol’s address is the one in use now').toBe(SECOND_MODEL_URL)
    expect(model.pending).toBeNull()
    expect(history.some((line) => line.area === 'model' && line.by === 'carol' && line.confirmed_by === 'bob')).toBe(true)
    expect(runs.plan.status, `the Planner answers with the confirmed model: ${JSON.stringify(runs.plan.body)}`).toBe(200)
    expect(runs.plan.body.decision, 'the Planner made a decision').toBeTruthy()
    expect(runs.run.status, `an agent run starts with the confirmed model: ${JSON.stringify(runs.run.body)}`).toBe(201)
    assertClean(watch)
    await context.close()
  })
})

test('@lane4 alice adds erin as an Operator, and erin has not signed in yet', async ({ browser }) => {
  await withApi(async (api) => {
    const { context, page, watch } = await as(browser, 'alice')
    await openSettings(page, 'people')
    await page.getByLabel('Work email').fill('erin@example.test')
    await page.getByLabel('Name', { exact: true }).fill('Erin')
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.locator('#people-notice')).toContainText('Added Erin.')
    await expect(page.locator('#people-notice')).toBeFocused()
    const row = personRow(page, 'erin@example.test')
    await expect(row).toContainText(NOT_SIGNED_IN)
    await expect(roleBox(page, 'Operator', 'Erin')).toBeChecked()
    await expect(roleBox(page, 'Approver', 'Erin')).not.toBeChecked()
    await shotTo(page, 4, 'p10-add-person.png')
    const erin = await api.person('erin@example.test')
    save(4, 'p10-add-person.json', { erin })
    expect(erin?.operator).toBe(true)
    expect(erin?.approver).toBe(false)
    expect(erin?.signed_in).toBe(false)
    assertClean(watch)
    await context.close()
  })
})

test('@lane5 alice ticks Approver for dave, and bob confirms it in Settings', async ({ browser }) => {
  await withApi(async (api) => {
    await api.ensurePerson('dave@example.test', 'Dave', { operator: true, approver: false })
    const alice = await as(browser, 'alice')
    await openSettings(alice.page, 'people')
    await roleBox(alice.page, 'Approver', 'Dave').click()
    await expect(alice.page.locator('#people-notice')).toContainText('Another Approver must confirm Dave as an Approver.')
    await expect(alice.page.locator('#people-notice'), 'the box is disabled now, so focus moves to the notice').toBeFocused()
    await expect(personRow(alice.page, 'dave@example.test')).toContainText('Approver: waiting for another Approver to confirm')
    await expect(personRow(alice.page, 'dave@example.test')).toContainText('Asked by you, so another Approver must confirm it.')
    await shotTo(alice.page, 5, 'p10-confirm-approver-asked.png')
    assertClean(alice.watch)
    await alice.context.close()

    const bob = await as(browser, 'bob')
    await openSettings(bob.page, 'people')
    const row = personRow(bob.page, 'dave@example.test')
    await expect(settingsTab(bob.page, 'People and roles')).toContainText('needs you')
    await expect(row.getByRole('button', { name: 'Confirm Dave as an Approver' })).toBeVisible()
    await shotTo(bob.page, 5, 'p10-confirm-approver.png')
    await row.getByRole('button', { name: 'Confirm Dave as an Approver' }).click()
    await expect(bob.page.locator('#people-notice')).toContainText('Dave is now an Approver.')
    await expect(bob.page.locator('#people-notice')).toBeFocused()
    await expect(roleBox(bob.page, 'Approver', 'Dave')).toBeChecked()
    await expect(row).not.toContainText('waiting for another Approver')
    await shotTo(bob.page, 5, 'p10-confirm-approver-done.png')
    const dave = await api.person('dave@example.test')
    save(5, 'p10-confirm-approver.json', { dave, history: (await api.history()).filter((line) => line.area === 'people').slice(0, 3) })
    expect(dave?.approver).toBe(true)
    expect(dave?.pending_approver).toBeNull()
    assertClean(bob.watch)
    await bob.context.close()
  })
})

test('@lane6 alice unticks erin’s Operator role, presses Undo, and erin is an Operator again', async ({ browser }) => {
  await withApi(async (api) => {
    const erin = await api.ensurePerson('erin@example.test', 'Erin', { operator: true, approver: true })
    if (!erin.approver) await api.confirmApprover(erin.id)
    const { context, page, watch } = await as(browser, 'alice')
    await openSettings(page, 'people')
    const box = roleBox(page, 'Operator', 'Erin')
    await expect(box).toBeChecked()
    await box.click()
    await expect(page.locator('#people-notice')).toContainText('Erin is no longer an Operator.')
    await expect(box).not.toBeChecked()
    await expect(box, 'focus stays on the box that was pressed').toBeFocused()
    const middle = await api.person('erin@example.test')
    await shotTo(page, 6, 'p10-undo-role-before.png')
    await page.locator('#people-notice').getByRole('button', { name: 'Undo' }).click()
    await expect(page.locator('#people-notice')).toContainText('Undone. Erin is an Operator again.')
    await expect(box).toBeChecked()
    await expect(box, 'Undo puts focus back on the box').toBeFocused()
    await shotTo(page, 6, 'p10-undo-role.png')
    const after = await api.person('erin@example.test')
    save(6, 'p10-undo-role.json', { afterUntick: middle, afterUndo: after })
    expect(middle?.operator).toBe(false)
    expect(after?.operator).toBe(true)
    assertClean(watch)
    await context.close()
  })
})

test('@lane7 unticking bob’s Approver role while only alice and bob are Approvers explains the rule and changes nothing', async ({ browser }) => {
  await withApi(async (api) => {
    await onlyAliceAndBobApprove(api)
    const historyBefore = await api.history()
    const { context, page, watch } = await as(browser, 'alice')
    const refusals: number[] = []
    page.on('response', (r) => {
      if (r.url().includes('/api/v1/people/bob/approver')) refusals.push(r.status())
    })
    await openSettings(page, 'people')
    const box = roleBox(page, 'Approver', 'Bob')
    await box.click()
    const row = personRow(page, 'bob@example.test')
    await expect(row).toContainText(TWO_APPROVERS)
    await expect(box).toBeChecked()
    await expect(box).toBeFocused()
    await expect(box).toHaveAttribute('aria-describedby', 'person-bob-error')
    await shotTo(page, 7, 'p10-floor.png')
    const bob = await api.person('bob@example.test')
    const historyAfter = await api.history()
    save(7, 'p10-floor.json', { refusals, bob, historyBefore: historyBefore.length, historyAfter: historyAfter.length, rowText: await row.innerText() })
    expect(refusals).toEqual([409])
    expect(bob?.approver).toBe(true)
    expect(historyAfter.length).toBe(historyBefore.length)
    assertClean(watch)
    await context.close()
  })
})

async function readOnlyState(page: Page) {
  return page.getByRole('main').evaluate((main) => {
    const fields = [...main.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input, select, textarea')]
    const buttons = [...main.querySelectorAll<HTMLButtonElement>('button')].map((b) => (b.textContent ?? '').trim())
    return {
      fields: fields.map((f) => ({ id: f.id, type: f.type, disabled: f.disabled })),
      buttons,
      forms: main.querySelectorAll('form').length,
    }
  })
}

async function expectReadOnly(page: Page, tab: 'model' | 'people') {
  await openSettings(page, tab)
  await expect(page.getByRole('main')).toContainText(ONLY_OPERATORS)
  const state = await readOnlyState(page)
  expect(state.forms, `${tab}: no form for bob`).toBe(0)
  expect(state.fields.filter((f) => !f.disabled), `${tab}: fields bob could change`).toEqual([])
  const decisions = state.buttons.filter((name) => !/^(AI model|People and roles)/.test(name))
  expect(decisions.every((name) => /^(Confirm|Not now)/.test(name)), `${tab}: buttons other than the tabs and a decision: ${decisions.join(', ')}`).toBe(true)
  return { ...state, decisions }
}

test('@lane8 bob sees every control read-only, and the page says only Operators change settings', async ({ browser }) => {
  const { context, page, watch } = await as(browser, 'bob')
  const states: Record<string, unknown> = {}
  for (const tab of ['model', 'people'] as const) {
    states[tab] = await expectReadOnly(page, tab)
    await shotTo(page, 8, tab === 'people' ? 'p10-read-only.png' : 'p10-read-only-model.png')
  }
  await withApi(async (api) => {
    await api.ensurePerson(WIDE_PENDING, 'Wide Pending', { operator: true, approver: true })
    expect((await api.confirmations('bob')).filter((c) => c.kind === 'approver' && c.you_can_decide).length, 'a request waits for bob').toBeGreaterThan(0)
  })
  const waiting = await expectReadOnly(page, 'people')
  states['people-with-a-request-waiting'] = waiting
  await shotTo(page, 8, 'p10-read-only-waiting.png')
  save(8, 'p10-read-only.json', states)
  expect(waiting.decisions.some((name) => name.startsWith('Confirm')), 'bob can confirm the waiting request').toBe(true)
  expect(waiting.decisions.some((name) => name.startsWith('Not now')), 'bob can say not now to the waiting request').toBe(true)
  assertClean(watch)
  await context.close()
})

// Lane 11 (D2 in the P10 recheck). Someone else takes people off the list while alice has People and roles open. The
// page names who left on its own line, keeps a notice or a refusal about someone still listed, and gives the line focus
// when the focused row left. Run on its own stack: it adds and removes people, and its last step needs alice and bob as
// the only Approvers.
const peopleSection = (page: Page) => page.locator('section[aria-labelledby="people-heading"]')
const leftLine = (page: Page) => page.locator('#people-left')

/** TanStack Query reads the list again when a browser tab comes back. */
async function returnToTab(page: Page): Promise<void> {
  await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
  await page.waitForTimeout(1_500)
}

async function said(page: Page) {
  const textOf = async (selector: string) => {
    const at = page.locator(selector)
    return (await at.count()) ? (await at.innerText()).trim() : null
  }
  return {
    left: await textOf('#people-left'),
    notice: await textOf('#people-notice'),
    problem: await textOf('#people-problem'),
    undo: await page.locator('#people-notice').getByRole('button', { name: 'Undo' }).count(),
    status: await peopleSection(page).locator('p.visually-hidden[role="status"]').allInnerTexts(),
    focus: await page.evaluate(() => {
      const at = document.activeElement
      return at === null || at === document.body ? 'body' : `${at.tagName.toLowerCase()}#${at.id}`
    }),
  }
}

test('@lane11 who left the People list is said on its own line, beside a notice or a refusal about someone still on it', async ({ browser }) => {
  test.setTimeout(300_000)
  const out: Record<string, unknown> = {}
  await withApi(async (api) => {
    await onlyAliceAndBobApprove(api)
    const tag = randomBytes(2).toString('hex')
    const add = async (name: string, approver = false): Promise<Person> => {
      const person = await api.ensurePerson(`${name.toLowerCase()}-${tag}@example.test`, `${name} ${tag}`, { operator: true, approver })
      if (approver && !person.approver) await api.confirmApprover(person.id)
      return person
    }
    const remove = async (person: Person) => (await api.send('carol', 'DELETE', `/api/v1/people/${person.id}`)).status
    const ivan = await add('Ivan')
    // Hana is an Approver too, so she keeps a role when alice unticks Operator.
    const hana = await add('Hana', true)
    const gina = await add('Gina')
    const jack = await add('Jack')
    const kim = await add('Kim')
    const lee = await add('Lee')
    const ned = await add('Ned')
    const pat = await add('Pat')
    const leftWords = (...people: Person[]) => {
      const names = people.map((p) => p.display)
      return `${names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1) ?? ''} are` : `${names[0] ?? ''} is`} ${LEFT}.`
    }
    const { context, page, watch } = await as(browser, 'alice')
    await openSettings(page, 'people')
    await expect(personRow(page, ivan.email)).toBeVisible()

    // a. Nothing was said. carol removes Ivan, and alice comes back to the tab.
    out['a-quiet'] = { removed: await remove(ivan) }
    await returnToTab(page)
    await expect(leftLine(page)).toContainText(leftWords(ivan))
    out['a-quiet'] = { ...(out['a-quiet'] as object), said: await said(page), row: await personRow(page, ivan.email).count() }

    // b. alice unticks Hana's Operator role, so focus is on Hana's box and the notice has Undo. Then carol removes Hana.
    const hanaBox = roleBox(page, 'Operator', hana.display)
    await hanaBox.click()
    await expect(page.locator('#people-notice')).toContainText(`${hana.display} is no longer an Operator.`)
    await expect(hanaBox).toBeFocused()
    const bBefore = await said(page)
    const bRemoved = await remove(hana)
    await returnToTab(page)
    await expect(leftLine(page)).toContainText(leftWords(hana))
    out['b-focused-row-leaves'] = { removed: bRemoved, before: bBefore, said: await said(page), row: await personRow(page, hana.email).count() }
    await shotTo(page, 11, 'p10-left-focused-row.png')

    // c. carol removes Gina, then alice ticks Approver for Gina before the list is read again.
    const cRemoved = await remove(gina)
    await roleBox(page, 'Approver', gina.display).click()
    // One line on the page says it, the left line or the page-level problem. A hidden status line reads it out.
    await expect(peopleSection(page).locator('#people-left, #people-problem').filter({ hasText: leftWords(gina) })).toHaveCount(1, { timeout: 15_000 })
    await page.waitForTimeout(800)
    out['c-act-on-someone-who-left'] = { removed: cRemoved, said: await said(page), row: await personRow(page, gina.email).count() }

    // d. Three leave at once.
    const dRemoved = [await remove(jack), await remove(kim), await remove(lee)]
    await returnToTab(page)
    await expect(leftLine(page)).toContainText(leftWords(jack, kim, lee))
    out['d-three-leave'] = { removed: dRemoved, said: await said(page) }

    // e. carol removes Ned, and alice adds Zed: "Added Zed" stays, and the left line names Ned.
    const eRemoved = await remove(ned)
    await page.getByLabel('Work email').fill(`zed-${tag}@example.test`)
    await page.getByLabel('Name', { exact: true }).fill(`Zed ${tag}`)
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.locator('#people-notice')).toContainText(`Added Zed ${tag}`)
    await expect(leftLine(page)).toContainText(`Ned ${tag} is ${LEFT}.`)
    await page.waitForTimeout(800)
    out['e-own-add-finds-a-removal'] = { removed: eRemoved, said: await said(page), nedRow: await personRow(page, ned.email).count() }
    await shotTo(page, 11, 'p10-left-beside-added.png')

    // f. bob's Approver box is refused (two Approvers at least), then carol removes Pat.
    const bobBox = roleBox(page, 'Approver', 'Bob')
    await bobBox.click()
    await expect(personRow(page, 'bob@example.test')).toContainText(TWO_APPROVERS)
    const fRemoved = await remove(pat)
    await returnToTab(page)
    await expect(leftLine(page)).toContainText(leftWords(pat))
    out['f-refusal-then-someone-leaves'] = {
      removed: fRemoved,
      said: await said(page),
      bobRow: await personRow(page, 'bob@example.test').innerText(),
      bobDescribedBy: await bobBox.getAttribute('aria-describedby'),
    }
    await shotTo(page, 11, 'p10-left-beside-refusal.png')
    save(11, 'p10-left-the-list.json', out)

    type Said = Awaited<ReturnType<typeof said>>
    const a = out['a-quiet'] as { said: Said; row: number }
    const b = out['b-focused-row-leaves'] as { said: Said; row: number }
    const c = out['c-act-on-someone-who-left'] as { said: Said; row: number }
    const d = out['d-three-leave'] as { said: Said }
    const e = out['e-own-add-finds-a-removal'] as { said: Said; nedRow: number }
    const f = out['f-refusal-then-someone-leaves'] as { said: Said; bobRow: string; bobDescribedBy: string | null }
    expect([a.row, b.row, c.row, e.nedRow], 'every removed row is gone').toEqual([0, 0, 0, 0])
    expect(a.said.status, 'a: a status line says who left').toContain(`${leftWords(ivan)} The list now shows who is on it.`)
    expect(b.said.notice, 'b: what was said on Hana’s row goes with the row').toBeNull()
    expect(b.said.undo, 'b: no Undo for a row that left').toBe(0)
    expect(b.said.focus, 'b: focus was on Hana’s box, so the left line takes it').toBe('div#people-left')
    const cSays = [c.said.left, c.said.problem].filter((line) => line?.includes(leftWords(gina)))
    expect(cSays, 'c: the page says Gina left once, not twice').toHaveLength(1)
    expect(c.said.focus, 'c: focus is on the line that says Gina left').toMatch(/^div#people-(left|problem)$/)
    expect(d.said.left, 'd: one line names all three').toContain(leftWords(jack, kim, lee))
    expect(e.said.notice, 'e: "Added Zed" stays').toContain(`Added Zed ${tag}`)
    expect(e.said.left, 'e: and the left line names Ned').toContain(`Ned ${tag} is ${LEFT}.`)
    expect(e.said.status.join(' | '), 'e: both are read out').toMatch(new RegExp(`Added Zed ${tag}.*\\| Ned ${tag} is ${LEFT}`))
    expect(f.bobRow, 'f: bob’s refusal stays on his row').toContain(TWO_APPROVERS)
    expect(f.bobDescribedBy, 'f: his box still points at it').toBe('person-bob-error')
    expect(f.said.left, 'f: and the left line names Pat').toContain(leftWords(pat))
    assertClean(watch)
    await context.close()
  })
})

// The sign-in checks on a stack with real sign-in through the mock identity provider (p10.sh signin). carol can sign
// in but is not on the People list, so Settings shows the ask screen and the platform refuses her the Settings data.
test('@signin-not-on-list carol signs in with real sign-in, is not on the list, and sees the ask screen, not Settings', async ({ browser }) => {
  test.skip(process.env['E2E_AUTH'] !== 'oidc', 'needs the oidc stack')
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-SG', timezoneId: 'Asia/Singapore' })
  const page = await context.newPage()
  const tokens: string[] = []
  page.on('response', async (r) => {
    if (r.request().method() !== 'POST' || r.url() !== `${MOCK_OIDC_URL}/token` || !r.ok()) return
    const body = (await r.json().catch(() => ({}))) as { access_token?: string }
    if (body.access_token) tokens.push(body.access_token)
  })
  const seen: { url: string; status: number }[] = []
  page.on('response', (r) => {
    if (new URL(r.url()).pathname.startsWith('/api/')) seen.push({ url: new URL(r.url()).pathname, status: r.status() })
  })
  await page.goto('/settings')
  const username = page.locator('input[name="username"]')
  await expect(username, 'a signed-out person goes to the identity provider').toBeVisible({ timeout: 60_000 })
  await username.fill('carol')
  await page.locator('input[type="submit"]').click()
  await expect(h1(page)).toHaveText('Ask an Operator to add you', { timeout: 30_000 })
  const atSettings = {
    url: page.url(),
    main: await page.getByRole('main').innerText(),
    tabs: await page.getByRole('group', { name: 'Settings sections' }).count(),
    settingsHeadings: await page.getByRole('heading', { level: 2, name: /AI model|People and roles/ }).count(),
    checkboxes: await page.getByRole('checkbox').count(),
  }
  await shotTo(page, 'signin', 'p10-not-on-list.png')
  await page.goto('/settings?tab=people')
  await expect(h1(page)).toHaveText('Ask an Operator to add you')
  const atPeople = { url: page.url(), tabs: await page.getByRole('group', { name: 'Settings sections' }).count(), checkboxes: await page.getByRole('checkbox').count() }
  const token = tokens.at(-1) ?? ''
  const http = await request.newContext({ baseURL: BASE_URL })
  const direct: Record<string, { status: number; body: string }> = {}
  try {
    for (const route of ['/api/v1/me', '/api/v1/people', '/api/v1/settings/model', '/api/v1/confirmations', '/api/v1/settings/history']) {
      const answer = await http.get(route, { headers: { Authorization: `Bearer ${token}` } })
      direct[route] = { status: answer.status(), body: (await answer.text()).slice(0, 300) }
    }
  } finally {
    await http.dispose()
  }
  save('signin', 'p10-not-on-list.json', { atSettings, atPeople, direct, seenByThePage: seen, hadToken: token.length > 0 })
  expect(token, 'the identity provider gave carol a token').not.toBe('')
  expect(atSettings.tabs, 'no Settings tabs').toBe(0)
  expect(atSettings.settingsHeadings, 'no Settings sections').toBe(0)
  expect(atSettings.checkboxes, 'no role boxes').toBe(0)
  expect(atPeople.tabs, 'no Settings tabs on the People link either').toBe(0)
  expect(direct['/api/v1/me']?.status).toBe(200)
  expect(direct['/api/v1/me']?.body).toContain('"on_list":false')
  for (const route of ['/api/v1/people', '/api/v1/settings/model', '/api/v1/confirmations', '/api/v1/settings/history']) expect(direct[route]?.status, route).toBe(403)
  await context.close()
})

interface AxeRun {
  readonly user: string
  readonly view: string
  readonly width: number
  readonly sidewaysScroll: boolean
  readonly violations: { id: string; impact: string | null | undefined; help: string; nodes: { target: unknown; summary: string | undefined }[] }[]
  readonly passes: number
}

async function axeRun(page: Page, user: string, view: string, phone: boolean): Promise<AxeRun> {
  await page.waitForTimeout(400)
  const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
  const width = phone ? 390 : 1440
  const scroll = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  await shotTo(page, 9, `p10-axe-${user}-${view}-${width}.png`)
  return {
    user,
    view,
    width,
    sidewaysScroll: scroll.scroll > scroll.client,
    violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
    passes: result.passes.length,
  }
}

test('@lane9 axe finds no WCAG 2.2 AA problems on either tab, the model list, the field errors or a refusal, at 1440 and 390 px', async ({ browser }) => {
  const runs: AxeRun[] = []
  await withApi(async (api) => {
    await onlyAliceAndBobApprove(api)
    // A long waiting line is the widest thing on the People tab, so the 390 px run needs one.
    await api.ensurePerson(WIDE_PENDING, 'Wide Pending', { operator: true, approver: true })
  })
  for (const user of ['alice', 'bob']) {
    for (const phone of [false, true]) {
      const { context, page } = await as(browser, user, phone)
      for (const tab of ['model', 'people'] as const) {
        await openSettings(page, tab)
        runs.push(await axeRun(page, user, tab, phone))
      }
      await context.close()
    }
  }
  for (const phone of [false, true]) {
    const { context, page } = await as(browser, 'alice', phone)
    await openSettings(page)
    await page.getByLabel('Provider').selectOption('other')
    await page.getByLabel('Address', { exact: true }).fill('')
    await page.getByRole('button', { name: 'Connect', exact: true }).click()
    await expect(page.locator('#model-address-error')).toBeVisible()
    runs.push(await axeRun(page, 'alice', 'model-field-errors', phone))
    await page.getByLabel('Address', { exact: true }).fill(MOCK_MODEL_URL)
    await page.getByLabel('API key').fill(freshKey('lane9'))
    await page.getByRole('button', { name: 'Connect', exact: true }).click()
    await expect(page.getByLabel('Model', { exact: true })).toBeVisible({ timeout: 30_000 })
    runs.push(await axeRun(page, 'alice', 'model-list', phone))
    await page.getByRole('button', { name: 'Cancel' }).click()
    await openSettings(page, 'people')
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.locator('#add-email-error')).toBeVisible()
    runs.push(await axeRun(page, 'alice', 'add-person-errors', phone))
    await roleBox(page, 'Approver', 'Bob').click()
    await expect(personRow(page, 'bob@example.test')).toContainText(TWO_APPROVERS)
    runs.push(await axeRun(page, 'alice', 'two-approver-refusal', phone))
    await context.close()
  }
  save(9, 'p10-axe.json', { tags: WCAG_22_AA, runs })
  const where = (r: AxeRun) => `${r.user} ${r.view} @${r.width}`
  expect(runs.flatMap((r) => r.violations.map((v) => `${where(r)}: ${v.id}`))).toEqual([])
  expect(runs.filter((r) => r.sidewaysScroll).map(where), 'pages that scroll sideways').toEqual([])
})

test('@lane10 after a key is saved, the full key is in no page source, no API response and no browser storage', async ({ browser }) => {
  await withApi(async (api) => {
    const key = freshKey('lane10')
    const secretPart = key.slice(0, -2)
    const responses: { method: string; url: string; status: number; holdsKey: boolean }[] = []
    const { context, page, watch } = await as(browser, 'alice')
    page.on('response', async (response) => {
      if (!response.url().includes('/api/')) return
      const body = await response.text().catch(() => '')
      responses.push({ method: response.request().method(), url: new URL(response.url()).pathname, status: response.status(), holdsKey: body.includes(secretPart) })
    })
    save(10, 'key-for-host-search.txt', `${key}\n`)
    await openSettings(page)
    await connectAndSave(page, { key })
    if (await page.locator('#model-waiting').isVisible()) await api.confirmAddress('bob')
    const afterSave = await everythingOnThePage(page)
    const keyField = await page.locator('#model-key').inputValue()
    const stores = await page.evaluate(async () => {
      const dump = (store: Storage) => Object.fromEntries(Object.keys(store).map((name) => [name, store.getItem(name)]))
      const databases = await indexedDB.databases()
      return { local: dump(localStorage), session: dump(sessionStorage), cookie: document.cookie, indexedDb: databases.map((db) => db.name ?? '') }
    })
    const storesHoldKey = JSON.stringify(stores).includes(secretPart)
    await page.reload()
    await expect(page.locator('#model-now')).toContainText(`API key ending ${key.slice(-2)}`)
    await page.getByText(/^Change history/).click()
    const afterReload = await everythingOnThePage(page)
    await settingsTab(page, 'People and roles').click()
    await expect(page.getByRole('heading', { level: 2, name: 'People and roles' })).toBeVisible()
    const peopleTab = await everythingOnThePage(page)
    const direct: Record<string, boolean> = {}
    for (const user of ['alice', 'bob', 'carol']) {
      for (const route of ['/api/v1/settings/model', '/api/v1/settings/history', '/api/v1/confirmations', '/api/v1/people', '/api/v1/me']) {
        direct[`${user} ${route}`] = JSON.stringify((await api.send(user, 'GET', route)).body).includes(secretPart)
      }
    }
    const found = [
      ...responses.filter((r) => r.holdsKey).map((r) => `response to ${r.method} ${r.url}`),
      ...(afterSave.includes(secretPart) ? ['page after saving'] : []),
      ...(afterReload.includes(secretPart) ? ['page after reload, history open'] : []),
      ...(peopleTab.includes(secretPart) ? ['People and roles tab'] : []),
      ...(storesHoldKey ? ['browser storage'] : []),
      ...(keyField ? ['the key field after saving'] : []),
      ...Object.entries(direct)
        .filter(([, holds]) => holds)
        .map(([where]) => where),
    ]
    const report = [
      `# Lane 10: the full key in the page, the API and browser storage (target ${TARGET})`,
      `key saved: ${key.length} characters, ending ${key.slice(-2)}; searched for its first ${secretPart.length}`,
      `browser API responses read: ${responses.length}`,
      ...responses.map((r) => `  ${r.method} ${r.url} ${r.status}: ${r.holdsKey ? 'HOLDS THE KEY' : 'clean'}`),
      `page after saving: ${afterSave.includes(secretPart) ? 'HOLDS THE KEY' : 'clean'} (${afterSave.length} characters, field values included)`,
      `page after reload with the history open: ${afterReload.includes(secretPart) ? 'HOLDS THE KEY' : 'clean'}`,
      `People and roles tab: ${peopleTab.includes(secretPart) ? 'HOLDS THE KEY' : 'clean'}`,
      `browser storage (local, session, cookies; IndexedDB ${stores.indexedDb.length === 0 ? 'has no databases' : `names ${stores.indexedDb.join(', ')}`}): ${storesHoldKey ? 'HOLDS THE KEY' : 'clean'}`,
      `key field after saving: ${keyField ? 'NOT EMPTY' : 'empty'}`,
      'direct GETs:',
      ...Object.entries(direct).map(([where, holds]) => `  ${where}: ${holds ? 'HOLDS THE KEY' : 'clean'}`),
      `verdict: ${found.length === 0 ? 'PASS, the full key appears nowhere' : `FAIL, found in ${found.join(', ')}`}`,
    ]
    save(10, 'p10-no-key.txt', `${report.join('\n')}\n`)
    expect(responses.length).toBeGreaterThan(0)
    expect(found).toEqual([])
    assertClean(watch)
    await context.close()
  })
})

test('@seed adds the perf probe’s people once', async () => {
  await withApi(async (api) => {
    for (let n = 1; n <= PERF_PEOPLE; n += 1) {
      const nn = String(n).padStart(2, '0')
      await api.ensurePerson(`perf-${nn}@example.test`, `Perf person ${nn}`, { operator: true, approver: false })
    }
    const perf = (await api.people()).filter((p) => p.email.startsWith('perf-'))
    save('perf', 'seeded.json', { people: perf.length })
    expect(perf.length).toBeGreaterThanOrEqual(PERF_PEOPLE)
  })
})

test('@perf largest contentful paint of People and roles, and when every row is drawn', async ({ browser }) => {
  const { context, page } = await as(browser, 'alice')
  await page.goto('/settings?tab=people', { waitUntil: 'commit' })
  const drawn = await page.waitForFunction(
    (least) => (document.querySelectorAll('ul[aria-label="People on the list"] > li').length >= least ? performance.now() : false),
    PERF_PEOPLE,
    { polling: 'raf', timeout: 15_000 },
  )
  const rowsDrawn = Number(await drawn.jsonValue())
  await page.waitForLoadState('load')
  const list = page.getByRole('list', { name: 'People on the list' }).getByRole('listitem')
  await expect(list).not.toHaveCount(0)
  const rows = await list.count()
  await page.waitForTimeout(1_500)
  const measured = await page.evaluate(
    () =>
      new Promise<{ entries: { startTime: number; element: string }[] }>((resolve) => {
        const entries: { startTime: number; element: string }[] = []
        const observer = new PerformanceObserver((found) => {
          for (const e of found.getEntries() as (PerformanceEntry & { element: Element | null })[]) {
            entries.push({ startTime: e.startTime, element: e.element ? `${e.element.tagName.toLowerCase()} "${(e.element.textContent ?? '').trim().slice(0, 40)}"` : 'gone' })
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => {
          observer.disconnect()
          resolve({ entries })
        }, 500)
      }),
  )
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, rows, lcp: last?.startTime ?? -1, rowsDrawn, element: last?.element ?? '', entries: measured.entries })
  expect(rows, 'the seeded people are on the list').toBeGreaterThanOrEqual(PERF_PEOPLE)
  await context.close()
})

test('@review-video alice connects a model and asks for a new Approver, and bob confirms both', async ({ browser }) => {
  test.setTimeout(240_000)
  await withApi(async (api) => {
    await api.ensurePerson('mei.ling@example.test', 'Mei Ling', { operator: true, approver: false })
    const context = await signedInAs(browser, 'alice', { video: path.join(EVID, '.review-video') })
    const page = await context.newPage()
    const video = page.video()
    await openSettings(page)
    await page.waitForTimeout(4_000)
    await page.getByLabel('Provider').selectOption('other')
    await page.getByLabel('Address', { exact: true }).pressSequentially(MOCK_MODEL_URL, { delay: 40 })
    await page.getByLabel('API key').pressSequentially(freshKey('video'), { delay: 15 })
    await page.waitForTimeout(800)
    await page.getByRole('button', { name: 'Connect', exact: true }).click()
    await expect(page.getByLabel('Model', { exact: true })).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(4_000)
    await page.getByLabel('Model', { exact: true }).selectOption(MOCK_MODEL)
    await page.getByRole('button', { name: 'Test and save' }).click()
    await expect(page.getByRole('button', { name: 'Connect', exact: true })).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(4_500)
    await settingsTab(page, 'People and roles').click()
    await page.waitForTimeout(1_500)
    await roleBox(page, 'Approver', 'Mei Ling').click()
    await expect(page.locator('#people-notice')).toContainText('Another Approver must confirm Mei Ling as an Approver.')
    await page.waitForTimeout(4_000)
    await page.getByRole('button', { name: 'Test controls' }).click()
    await page.getByRole('region', { name: 'Test controls' }).getByRole('button', { name: 'Bob' }).click()
    await page.getByRole('button', { name: 'Hide test controls' }).click()
    await expect(personRow(page, 'mei.ling@example.test').getByRole('button', { name: 'Confirm Mei Ling as an Approver' })).toBeVisible()
    await page.waitForTimeout(3_500)
    await personRow(page, 'mei.ling@example.test').getByRole('button', { name: 'Confirm Mei Ling as an Approver' }).click()
    await expect(page.locator('#people-notice')).toContainText('Mei Ling is now an Approver.')
    await page.waitForTimeout(4_000)
    await settingsTab(page, 'AI model').click()
    const confirm = page.locator('#model-waiting').getByRole('button', { name: 'Confirm address' })
    if (await confirm.isVisible().catch(() => false)) {
      await page.waitForTimeout(4_000)
      await confirm.click()
      await expect(page.locator('#model-now')).toContainText(`Confirmed. Runs now use ${MOCK_MODEL}.`)
    }
    await page.waitForTimeout(4_000)
    await context.close()
    await video?.saveAs(path.join(EVID, 'p10-review.webm'))
  })
})
