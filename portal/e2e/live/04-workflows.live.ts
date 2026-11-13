import { randomUUID } from 'node:crypto'
import type { APIRequestContext, Page } from '@playwright/test'
import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { MOCK_MODEL, MOCK_MODEL_URL, SettingsApi } from './support/settings'
import { expect, test } from './support/test'
import { devContext, expectReadOnly, OUT, shot } from './support/ui'

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
const rowOf = (page: Page, useCaseId: string) => page.locator(`li[data-workflow-id="${useCaseId}"]`)
const nextRun = (page: Page) => page.locator('section', { has: page.getByRole('heading', { name: 'When', exact: true }) }).locator('p')
const changeWhen = (page: Page) => page.getByRole('button', { name: /^(Change|Set) when it runs$/ })
const versionsList = (page: Page) => page.getByRole('list', { name: 'Versions, newest first' })

/** Versions is a details, closed until opened. */
async function openVersions(page: Page): Promise<void> {
  const summary = page.locator('summary', { hasText: 'Versions' })
  if ((await versionsList(page).count()) === 0 || !(await versionsList(page).isVisible())) await summary.click()
}
const moreActions = (page: Page) => page.getByRole('button', { name: 'More actions' })
const menuItem = (page: Page, name: string) => page.getByRole('menuitem', { name })

/** Opens More actions with the mouse and picks one item. */
async function pickFromMenu(page: Page, name: string): Promise<void> {
  await moreActions(page).click()
  await menuItem(page, name).click()
}
const VERSION_CHECKER = { card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }

async function connectMockModel(baseURL: string): Promise<void> {
  const settings = await SettingsApi.connect(baseURL)
  try {
    if ((await settings.model()).active?.base_url === MOCK_MODEL_URL) return
    const saved = await settings.send<{ status: string }>('alice', 'PUT', '/api/v1/settings/model', { style: 'anthropic', base_url: MOCK_MODEL_URL, model: MOCK_MODEL, api_key: 'p9-live-key-not-real' })
    expect(saved.status, `alice saves the mock model: ${JSON.stringify(saved.body)}`).toBe(200)
    await settings.confirmAddress('bob')
    expect((await settings.model()).active?.base_url, 'the mock model is active').toBe(MOCK_MODEL_URL)
  } finally {
    await settings.dispose()
  }
}

async function agentWorkflow(request: APIRequestContext, label: string): Promise<{ id: string; name: string }> {
  const name = `p9 ${label} ${randomUUID().slice(0, 6)}`
  const response = await request.post('/api/v1/agent-use-cases', {
    headers: { 'X-Dev-User': 'alice' },
    data: { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [VERSION_CHECKER] },
  })
  expect(response.status(), 'alice makes an agent workflow').toBe(201)
  return { id: ((await response.json()) as { use_case_id: string }).use_case_id, name }
}

test('alice opens a workflow from Workflows, presses Run now, and lands on the new run’s page', async ({ browser, backend, request, baseURL }, info) => {
  await connectMockModel(String(baseURL))
  const workflow = await agentWorkflow(request, 'run now')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(heading(page)).toHaveText('Workflows')
  const row = rowOf(page, workflow.id)
  await expect(row).toContainText('On')
  await expect(row.getByRole('link')).toContainText(workflow.name)
  await row.getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/workflows/${workflow.id}$`))
  await expect(heading(page)).toHaveText(workflow.name)
  await shot(page, info, 'p9-04-workflow-page')

  await expect(page.getByRole('button', { name: 'Run now' }), 'Run now lives in More actions').toHaveCount(0)
  await pickFromMenu(page, 'Run now')
  await expect(page).toHaveURL(/\/runs\/run_[A-Za-z0-9]+$/)
  const runId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
  const run = await backend.run(runId)
  expect(run.use_case_name).toBe(workflow.name)
  expect(run.started_by).toBe('alice')
  expect((await backend.runs('alice')).filter((r) => r.use_case_name === workflow.name)).toHaveLength(1)
  await expect(heading(page)).toBeVisible()
  await shot(page, info, 'p9-04-run-now')
  await context.close()
})

test('alice pauses a workflow, its next run reads Paused and Run now goes, and resuming brings them back', async ({ browser, request }) => {
  const workflow = await agentWorkflow(request, 'pause')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)
  await expect(nextRun(page)).toContainText('Next run: Not scheduled')

  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(nextRun(page)).toContainText('Next run: Paused')
  await expect(page.getByRole('main')).toContainText('Paused. It won’t run until you resume it.')
  await expect(page.getByRole('button', { name: 'Resume' })).toBeFocused()
  await expect(page.getByRole('button', { name: 'Pause' })).toHaveCount(0)
  await moreActions(page).click()
  await expect(menuItem(page, 'Run now')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Resume' }).click()
  await expect(nextRun(page)).toContainText('Next run: Not scheduled')
  await expect(page.getByRole('button', { name: 'Pause' })).toBeFocused()
  await moreActions(page).click()
  await expect(menuItem(page, 'Run now')).toBeVisible()
  await context.close()
})

test('every workflow row, Needs you row and Recent runs row is a target of at least 44 px, at 1440 and 390 px', async ({ browser, backend, request, baseURL }) => {
  await connectMockModel(String(baseURL))
  const workflow = await agentWorkflow(request, 'targets')
  await backend.checkNow('alice', workflow.id)
  for (const phone of [false, true]) {
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    await page.goto('/workflows')
    await expect(rowOf(page, workflow.id)).toBeVisible()
    const links = page.getByRole('main').locator('li[data-workflow-id] > a, li[data-home-item] > a')
    const count = await links.count()
    expect(count, 'the page has rows to measure').toBeGreaterThan(0)
    for (let index = 0; index < count; index += 1) {
      const box = await links.nth(index).boundingBox()
      expect(box?.height ?? 0, `row ${String(index)} is at least 44 px tall at ${phone ? 390 : 1440} px`).toBeGreaterThanOrEqual(44)
    }
    await page.goto(`/workflows/${workflow.id}`)
    const runs = page.getByRole('region', { name: 'Recent runs' }).getByRole('link')
    await expect(runs.first()).toBeVisible()
    for (const box of await Promise.all((await runs.all()).map((link) => link.boundingBox()))) expect(box?.height ?? 0, 'a Recent runs row is at least 44 px tall').toBeGreaterThanOrEqual(44)
    await context.close()
  }
})

test('alice deletes a workflow, it leaves the list, and Undo puts it back', async ({ browser, request }, info) => {
  const { id: useCaseId, name } = await agentWorkflow(request, 'delete')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${useCaseId}`)
  await expect(heading(page)).toHaveText(name)
  await pickFromMenu(page, 'Delete')
  const dialog = page.getByRole('alertdialog', { name: `Delete ${name}?` })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('its schedule stops')
  await expect(dialog).toContainText('Undo stays in the message that follows.')
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(moreActions(page), 'Cancel hands focus back to More actions').toBeFocused()
  await expect(heading(page)).toHaveText(name)
  await pickFromMenu(page, 'Delete')
  await dialog.getByRole('button', { name: 'Delete workflow' }).click()

  await expect(page).toHaveURL(/\/workflows$/)
  await expect(page.getByRole('button', { name: 'Undo' })).toBeFocused()
  await expect(rowOf(page, useCaseId)).toHaveCount(0)
  await shot(page, info, 'p9-04-deleted')
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(rowOf(page, useCaseId)).toBeVisible()
  await expect(rowOf(page, useCaseId).getByRole('link')).toBeFocused()
  await expect(page.getByText('Put back.', { exact: true }).last()).toBeVisible()
  const listed = await request.get('/api/v1/use-cases', { headers: { 'X-Dev-User': 'alice' } })
  expect(((await listed.json()) as { use_cases: { use_case_id: string }[] }).use_cases.map((item) => item.use_case_id)).toContain(useCaseId)
  await context.close()
})

test('bob sees who may approve and the recent runs, with no Run now, Pause or Delete', async ({ browser, backend, request, baseURL }, info) => {
  await connectMockModel(String(baseURL))
  const workflow = await agentWorkflow(request, 'approver')
  await backend.checkNow('alice', workflow.id)
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)
  await expect(page.getByRole('main')).toContainText('Any Approver except the people who start or own it')
  await expect(page.getByRole('region', { name: 'Recent runs' }).getByRole('link').first()).toBeVisible()
  for (const name of ['Run now', 'Pause', 'Resume', 'Delete', 'More actions', 'Change when it runs', 'Set when it runs']) await expect(page.getByRole('button', { name })).toHaveCount(0)
  await expectReadOnly(page, 'this workflow')
  await shot(page, info, 'p9-04-approver')
  await page.goto('/workflows')
  await expect(rowOf(page, workflow.id)).toBeVisible()
  await expectReadOnly(page, 'workflows')
  for (const name of ['Run now', 'Pause', 'Resume', 'Delete', 'Discard']) await expect(page.getByRole('main').getByRole('button', { name })).toHaveCount(0)
  await context.close()
})

test('the Software watchlist opens on the Software page, from its row and from its old address', async ({ browser, backend }) => {
  const watchlist = await backend.freshWatchlist('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const link = rowOf(page, watchlist).getByRole('link')
  await expect(link).toContainText('Software watchlist')
  await expect(link).toHaveAttribute('href', '/software')
  await link.click()
  await expect(page).toHaveURL(/\/software$/)
  await expect(heading(page)).toHaveText('Watchlist')
  await page.goto(`/workflows/${watchlist}`)
  await expect(page).toHaveURL(/\/software$/)
  await expect(heading(page)).toHaveText('Watchlist')
  await context.close()
})

test('scenario H: alice changes the schedule, pauses and deletes through the page, every menu step by keyboard', async ({ browser, request }, info) => {
  const workflow = await agentWorkflow(request, 'scenario h')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)

  const order = await page.evaluate(() => {
    const at = (needle: string) => document.body.innerText.indexOf(needle)
    return ['On. It has no schedule', 'Who says yes', 'Recent runs', 'Agents'].map(at)
  })
  expect(order.every((place) => place >= 0), 'every section is on the page').toBe(true)
  expect(order, 'banner, who says yes, recent runs, then the agents').toEqual([...order].sort((a, b) => a - b))

  await moreActions(page).focus()
  await expect(moreActions(page)).toHaveAttribute('aria-haspopup', 'menu')
  await expect(moreActions(page)).toHaveAttribute('aria-expanded', 'false')
  await page.keyboard.press('Enter')
  await expect(moreActions(page)).toHaveAttribute('aria-expanded', 'true')
  await expect(menuItem(page, 'Run now')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menuItem(page, 'Delete')).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menuItem(page, 'Run now'), 'the arrow keys wrap').toBeFocused()
  await page.keyboard.press('End')
  await expect(menuItem(page, 'Delete')).toBeFocused()
  await page.keyboard.press('Home')
  await expect(menuItem(page, 'Run now')).toBeFocused()
  await expectAccessible(page, path.join(OUT, 'axe'), 'workflow-page-menu-open')
  await shot(page, info, 'n16-menu-open')
  await page.keyboard.press('Escape')
  await expect(moreActions(page)).toHaveAttribute('aria-expanded', 'false')
  await expect(moreActions(page), 'Escape returns focus to the button').toBeFocused()

  await changeWhen(page).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('form', { name: 'Change when it runs' })).toBeVisible()
  await expect(page.getByLabel('Day')).toBeFocused()
  await page.getByLabel('Day').selectOption('monday')
  await page.getByLabel('Time, Singapore').fill('09:00')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('form', { name: 'Change when it runs' })).toHaveCount(0)
  await expect(page.getByRole('main')).toContainText('Every Monday at 9:00')
  await expect(page.getByRole('main')).toContainText('Set by Alice.')
  await expect(changeWhen(page), 'focus returns to Change, the control that opened the editor').toBeFocused()

  await page.getByRole('button', { name: 'Pause' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toContainText('Paused. It won’t run until you resume it.')
  await expect(page.getByRole('button', { name: 'Resume' })).toBeFocused()
  await shot(page, info, 'n16-paused')

  await moreActions(page).focus()
  await page.keyboard.press('Enter')
  await page.keyboard.press('End')
  await expect(menuItem(page, 'Delete')).toBeFocused()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('alertdialog', { name: `Delete ${workflow.name}?` })
  await expect(dialog).toContainText('its schedule stops')
  await expect(dialog.getByRole('button', { name: 'Cancel' }), 'the safe choice has focus').toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(moreActions(page)).toBeFocused()
  const kept = await request.get(`/api/v1/use-cases/${workflow.id}`, { headers: { 'X-Dev-User': 'alice' } })
  expect(kept.status(), 'cancelling deleted nothing').toBe(200)

  await page.keyboard.press('Enter')
  await page.keyboard.press('End')
  await page.keyboard.press('Enter')
  await dialog.getByRole('button', { name: 'Delete workflow' }).click()
  await expect(page).toHaveURL(/\/workflows$/)
  await expect(page.getByRole('button', { name: 'Undo' })).toBeFocused()
  await context.close()
})

async function saveSchedule(request: APIRequestContext, user: string, useCaseId: string, data: Record<string, string>): Promise<void> {
  const response = await request.put(`/api/v1/use-cases/${useCaseId}/schedule`, { headers: { 'X-Dev-User': user }, data })
  expect(response.status(), `${user} saves the schedule: ${await response.text()}`).toBe(200)
}

async function undo(request: APIRequestContext, user: string, useCaseId: string, version: number) {
  return request.post(`/api/v1/use-cases/${useCaseId}/versions/${version}/undo`, { headers: { 'X-Dev-User': user }, data: { via: 'chat' } })
}

test('alice’s schedule changes publish versions the page lists read only, an Undo shows as a new version, a stale Undo is refused, and bob reads the same list', async ({ browser, request }, info) => {
  const workflow = await agentWorkflow(request, 'versions')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)
  await expect(page.locator('summary', { hasText: 'Versions' }), 'one version shows no list').toHaveCount(0)

  await changeWhen(page).click()
  await page.getByLabel('Day').selectOption('weekdays')
  await page.getByLabel('Time, Singapore').fill('08:00')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await openVersions(page)
  const newest = versionsList(page).getByRole('listitem').first()
  await expect(versionsList(page).getByRole('listitem')).toHaveCount(2)
  await expect(newest).toContainText(/Version 2, in use\s*Today, \d{1,2}:\d\d\. Alice set it to run every weekday at 8:00\./)
  await expect(versionsList(page).getByRole('listitem').last()).toContainText('Version 1The version it was turned on with.')

  await saveSchedule(request, 'alice', workflow.id, { day: 'monday', at: '08:00', via: 'chat' })
  await page.reload()
  await openVersions(page)
  await expect(newest).toContainText('Version 3, in use')
  await expect(newest).toContainText('Alice changed when it runs from every weekday at 8:00 to every Monday at 8:00.')

  const undone = await undo(request, 'alice', workflow.id, 3)
  expect(undone.status(), `alice undoes version 3 from the chat: ${await undone.text()}`).toBe(200)
  await page.reload()
  await openVersions(page)
  await expect(newest).toContainText('Alice undid version 3, so it runs every weekday at 8:00 again.')
  await expect(page.getByRole('main')).toContainText('Every weekday at 8:00')
  await expect(page.getByRole('button', { name: /^Undo/ }), 'the page only reads: Undo is on the chat’s edit card').toHaveCount(0)

  await saveSchedule(request, 'carol', workflow.id, { day: 'friday', at: '17:30' })
  const stale = await undo(request, 'alice', workflow.id, 4)
  expect(stale.status(), 'an Undo with a later version is refused').toBe(409)
  expect(await stale.json()).toEqual({ detail: 'The workflow changed again since this version, so Undo would throw that change away.' })
  await page.reload()
  await openVersions(page)
  await expect(versionsList(page).getByRole('listitem'), 'the stale Undo published nothing').toHaveCount(5)
  await expect(newest).toContainText('Carol changed when it runs from every weekday at 8:00 to every Friday at 17:30.')

  const bobContext = await devContext(browser, 'bob')
  const bob = await bobContext.newPage()
  await bob.goto(`/workflows/${workflow.id}`)
  await openVersions(bob)
  await expect(versionsList(bob).getByRole('listitem')).toHaveCount(5)
  await expect(bob.getByRole('button', { name: /^Undo/ })).toHaveCount(0)
  await expectReadOnly(bob, 'this workflow')

  for (const [who, reader] of [['alice', page], ['bob', bob]] as const) {
    for (const width of [1920, 1280, 900, 390]) {
      await reader.setViewportSize({ width, height: 900 })
      await reader.locator('summary', { hasText: 'Versions' }).scrollIntoViewIfNeeded()
      const widths = await reader.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
      expect(widths[0], `${who}’s page does not scroll sideways at ${width} px`).toBeLessThanOrEqual(widths[1] ?? 0)
      await shot(reader, info, `r6-versions-${who}-${width}`)
    }
  }
  await expectAccessible(page, path.join(OUT, 'axe'), 'workflow-page-versions')
  await bobContext.close()
  await context.close()
})

for (const phone of [false, true]) {
  test(`the workflow page passes WCAG 2.2 AA, keeps reduced motion calm and does not scroll sideways at ${phone ? '390' : '1440'} px`, async ({ browser, request }, info) => {
    const workflow = await agentWorkflow(request, phone ? 'phone' : 'desktop')
    const context = await devContext(browser, 'alice', { phone, reducedMotion: true })
    const page = await context.newPage()
    await page.goto(`/workflows/${workflow.id}`)
    await expect(heading(page)).toHaveText(workflow.name)
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await expectAccessible(page, path.join(OUT, 'axe'), `workflow-page-${phone ? 'phone' : 'desktop'}`)
    await moreActions(page).click()
    await expect(menuItem(page, 'Delete')).toBeVisible()
    const animating = await page.evaluate(() => document.getAnimations().filter((a) => a.effect?.getTiming().iterations === Infinity).length)
    expect(animating, 'no infinite animation runs under reduced motion').toBe(0)
    await expectAccessible(page, path.join(OUT, 'axe'), `workflow-page-menu-${phone ? 'phone' : 'desktop'}`)
    for (const name of ['Pause', 'More actions', 'Run now', 'Delete']) {
      const box = await page.getByRole(name === 'Run now' || name === 'Delete' ? 'menuitem' : 'button', { name }).first().boundingBox()
      expect(box?.height ?? 0, `${name} is at least 44 px tall`).toBeGreaterThanOrEqual(44)
    }
    const set = await changeWhen(page).boundingBox()
    expect(set?.height ?? 0, 'Set when it runs is at least 44 px tall').toBeGreaterThanOrEqual(44)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'the page does not scroll sideways').toBeLessThanOrEqual(widths[1] ?? 0)
    await shot(page, info, `n16-workflow-${phone ? 'phone' : 'desktop'}`)
    await context.close()
  })
}

test('Escape on the delete dialog closes it at once, and the next Enter keeps focus in the menu it opens', async ({ browser, request }) => {
  test.setTimeout(120_000)
  const workflow = await agentWorkflow(request, 'escape')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows/${workflow.id}`)
  await expect(heading(page)).toHaveText(workflow.name)
  const dialog = page.getByRole('alertdialog')
  for (const round of [1, 2, 3, 4, 5, 6, 7, 8]) {
    await moreActions(page).focus()
    await page.keyboard.press('Enter')
    await page.keyboard.press('End')
    await expect(menuItem(page, 'Delete'), `round ${round}: Delete has focus`).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(dialog.getByRole('button', { name: 'Cancel' }), `round ${round}: Cancel has focus`).toBeFocused()
    await page.keyboard.press('Escape')
    await page.keyboard.press('Enter')
    await expect(menuItem(page, 'Run now'), `round ${round}: the menu opened and has focus`).toBeFocused()
    await page.waitForTimeout(250)
    await expect(dialog, `round ${round}: the dialog stayed closed`).toHaveCount(0)
    await expect(menuItem(page, 'Run now'), `round ${round}: nothing took focus out of the menu`).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(moreActions(page)).toBeFocused()
  }
  const kept = await request.get(`/api/v1/use-cases/${workflow.id}`, { headers: { 'X-Dev-User': 'alice' } })
  expect(kept.status(), 'cancelling deleted nothing').toBe(200)
  await context.close()
})
