import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
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
    const offered = await models.locator('option').allInnerTexts()
    await models.selectOption(MOCK_MODEL)
    await page.getByRole('button', { name: 'Test and save' }).click()
    await expect(page.getByRole('button', { name: 'Connect', exact: true })).toBeVisible({ timeout: 30_000 })
    const waited = await page.locator('#model-waiting').isVisible()
    if (waited) await api.confirmAddress('bob')
    await page.reload()
    await expect(page.locator('#model-now')).toContainText(`API key ending ${key.slice(-2)}`)
    await expect(page.locator('#model-now')).toContainText(MOCK_MODEL)
    await shotTo(page, 1, 'p10-model.png')
    const everything = await everythingOnThePage(page)
    const model = await api.model('alice')
    save(1, 'p10-model.json', { offered, waitedForAnApprover: waited, active: model.active, keyEnding: key.slice(-2) })
    expect(offered.some((option) => option.includes(MOCK_MODEL)), `the model list offers ${MOCK_MODEL}: ${offered.join(', ')}`).toBe(true)
    expect(model.active?.base_url).toBe(MOCK_MODEL_URL)
    expect(model.active?.key_hint).toBe(key.slice(-2))
    expect(everything.includes(key.slice(0, -2)), 'more of the key than its last two characters is on the page').toBe(false)
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 carol enters an address that is not on the known list, and it waits for an Approver', async ({ browser }) => {
  await withApi(async (api) => {
    const before = await api.model('alice')
    const { context, page, watch } = await as(browser, 'carol')
    await openSettings(page)
    await connectAndSave(page, { key: freshKey('lane2') })
    const waiting = page.locator('#model-waiting')
    await expect(waiting, 'a fresh stack has never confirmed the mock model, so it waits').toBeVisible()
    await expect(waiting).toContainText('A new address is waiting for an Approver')
    await expect(waiting).toContainText('Entered by Carol')
    await expect(waiting.getByRole('button', { name: 'Confirm address' })).toHaveCount(0)
    await shotTo(page, 2, 'p10-pending-address.png')
    const after = await api.model('alice')
    save(2, 'p10-pending-address.json', { before: before.active, after: after.active, pending: after.pending })
    expect(after.pending?.by).toBe('carol')
    expect(after.pending?.base_url).toBe(MOCK_MODEL_URL)
    expect(after.active, 'runs keep the old model').toEqual(before.active)
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 bob confirms carol’s address, the new model is in use, and the history names both', async ({ browser }) => {
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
    save(3, 'p10-address-confirmed.json', { active: model.active, pending: model.pending, history: history.filter((line) => line.area === 'model') })
    expect(model.active?.base_url).toBe(MOCK_MODEL_URL)
    expect(model.pending).toBeNull()
    expect(history.some((line) => line.area === 'model' && line.by === 'carol' && line.confirmed_by === 'bob')).toBe(true)
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
    const approvers = (await api.people()).filter((p) => p.approver).map((p) => p.id)
    expect(approvers.sort(), 'this lane needs a stack where only alice and bob are Approvers').toEqual(['alice', 'bob'])
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

test('@lane8 bob sees every control read-only, and the page says only Operators change settings', async ({ browser }) => {
  const { context, page, watch } = await as(browser, 'bob')
  const states: Record<string, unknown> = {}
  for (const tab of ['model', 'people'] as const) {
    await openSettings(page, tab)
    await expect(page.getByRole('main')).toContainText(ONLY_OPERATORS)
    const state = await readOnlyState(page)
    states[tab] = state
    await shotTo(page, 8, tab === 'people' ? 'p10-read-only.png' : 'p10-read-only-model.png')
    expect(state.forms, `${tab}: no form for bob`).toBe(0)
    expect(state.fields.filter((f) => !f.disabled), `${tab}: fields bob could change`).toEqual([])
    const decisions = state.buttons.filter((name) => !/^(AI model|People and roles)/.test(name))
    expect(decisions.every((name) => /^(Confirm|Not now)/.test(name)), `${tab}: buttons other than the tabs and a decision: ${decisions.join(', ')}`).toBe(true)
  }
  save(8, 'p10-read-only.json', states)
  assertClean(watch)
  await context.close()
})

test('@lane9 axe finds no WCAG 2.2 AA problems on either tab at 1440 and 390 px', async ({ browser }) => {
  const runs: Record<string, unknown>[] = []
  // A long waiting line is the widest thing on the People tab, so the 390 px run needs one.
  await withApi((api) => api.ensurePerson('wide-pending@example.test', 'Wide Pending', { operator: true, approver: true }))
  for (const user of ['alice', 'bob']) {
    for (const phone of [false, true]) {
      const { context, page } = await as(browser, user, phone)
      for (const tab of ['model', 'people'] as const) {
        await openSettings(page, tab)
        await page.waitForTimeout(400)
        const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
        const width = phone ? 390 : 1440
        const scroll = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
        runs.push({
          user,
          tab,
          width,
          sidewaysScroll: scroll.scroll > scroll.client,
          violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
          passes: result.passes.length,
        })
        await shotTo(page, 9, `p10-axe-${user}-${tab}-${width}.png`)
      }
      await context.close()
    }
  }
  save(9, 'p10-axe.json', { tags: WCAG_22_AA, runs })
  const problems = runs.flatMap((r) => (r['violations'] as { id: string }[]).map((v) => `${String(r['user'])} ${String(r['tab'])} @${String(r['width'])}: ${v.id}`))
  expect(problems).toEqual([])
  expect(runs.filter((r) => r['sidewaysScroll']).map((r) => `${String(r['user'])} ${String(r['tab'])} @${String(r['width'])}`), 'pages that scroll sideways').toEqual([])
})

test('@lane10 after a key is saved, the full key is in no page source and no API response', async ({ browser }) => {
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
    await openSettings(page)
    await connectAndSave(page, { key })
    if (await page.locator('#model-waiting').isVisible()) await api.confirmAddress('bob')
    const afterSave = await everythingOnThePage(page)
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
      ...Object.entries(direct)
        .filter(([, holds]) => holds)
        .map(([where]) => where),
    ]
    const report = [
      `# Lane 10: the full key in the page and the API (target ${TARGET})`,
      `key saved: ${key.length} characters, ending ${key.slice(-2)}; searched for its first ${secretPart.length}`,
      `browser API responses read: ${responses.length}`,
      ...responses.map((r) => `  ${r.method} ${r.url} ${r.status}: ${r.holdsKey ? 'HOLDS THE KEY' : 'clean'}`),
      `page after saving: ${afterSave.includes(secretPart) ? 'HOLDS THE KEY' : 'clean'} (${afterSave.length} characters, field values included)`,
      `page after reload with the history open: ${afterReload.includes(secretPart) ? 'HOLDS THE KEY' : 'clean'}`,
      `People and roles tab: ${peopleTab.includes(secretPart) ? 'HOLDS THE KEY' : 'clean'}`,
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

test('@perf largest contentful paint of People and roles', async ({ browser }) => {
  const { context, page } = await as(browser, 'alice')
  await page.goto('/settings?tab=people', { waitUntil: 'load' })
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
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, rows, lcp: last?.startTime ?? -1, element: last?.element ?? '', entries: measured.entries })
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
