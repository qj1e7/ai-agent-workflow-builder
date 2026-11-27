import type { Page } from '@playwright/test'
import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { outOfVisualOrder, walkTabs, withoutVisibleFocus } from '../support/keyboard'
import { connectMockModel } from './support/settings'
import { expect, test } from './support/test'
import { openContext, OUT, shot } from './support/ui'

/** The small line above Home's heading, as in the chat-first sketch. */
const GREETING = (name: string) => new RegExp(`^Good (morning|afternoon|evening), ${name}$`)
/** An Operator's Home asks the sketch's question, on day one too. */
const HOME_ALICE = 'What can I help you with today?'

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

const RAIL = [
  { label: 'Home', path: '/', heading: HOME_ALICE },
  { label: 'Workflows', path: '/workflows', heading: 'Workflows' },
] as const

const PAGES = [...RAIL.map(({ path: to, label }) => ({ label, path: to })), { label: 'Settings', path: '/settings' }]

/** Axe reads colours as they are drawn, so it waits for a panel's opening animation to end. */
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().length === 0)

const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Browse' })
/** The rail's three items, above its foot of Teams, the practice Jira, Settings and the person. */
const railItems = (page: Page) => mainMenu(page).getByRole('list').getByRole('link')
const heading = (page: Page) => page.getByRole('heading', { level: 1 })

async function slowHome(page: Page): Promise<void> {
  await page.route('**/api/v1/home', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300))
    await route.continue()
  })
}

/** An Operator's Home is drawn once its box is there, and an Approver's once Needs you or All quiet is. */
async function loaded(page: Page): Promise<void> {
  const main = page.getByRole('main')
  await expect(main.getByRole('status').filter({ hasText: /^Loading/ })).toHaveCount(0)
  if (new URL(page.url()).pathname !== '/') return
  const drawn = main.locator('[data-home-item]').or(main.getByText('All quiet', { exact: true })).or(main.locator('#planner-box'))
  await expect(drawn.first()).toBeVisible()
  // The chips wait on the watchlist and the capability registry, which can answer after the box draws.
  await expect(main.getByRole('group', { name: /^(Suggestions|Starting points)$/ }).getByRole('button').first()).toBeVisible()
}

/** A rail link's text. The count sits beside the name, so a reused stack with something waiting reads “Workflows2”. */
const linkText = (label: string) => new RegExp(`^${label}\\d*$`)

/** A rail link's name, which carries its count once known: Home's Needs you, and the others' totals (ADR 0052). */
const linkName = (label: string) => new RegExp(label === 'Home' ? '^Home(, (1 thing needs|\\d+ things need) you)?$' : `^${label}(, \\d+ in all)?$`)

test('Home greets the signed-in person and the rail reads Home, Workflows', async ({ page }, info) => {
  await page.goto('/')
  await expect(heading(page)).toHaveText(HOME_ALICE)
  await expect(page.getByRole('main').getByText(GREETING('Alice'))).toBeVisible()
  await expect(page.getByRole('banner'), 'the top bar is gone').toHaveCount(0)
  await expect(mainMenu(page)).toContainText('Alice, Operator and Approver')
  await expect(railItems(page)).toHaveText(RAIL.map((item) => linkText(item.label)))
  await expect(mainMenu(page).getByRole('link', { name: 'New workflow' }), 'New workflow has no entry in the rail').toHaveCount(0)
  await expect(mainMenu(page).getByRole('link', { name: linkName('Home') })).toHaveAttribute('aria-current', 'page')
  await expect(page).toHaveTitle('What can I help you with today? · AI Workflow Builder')
  await shot(page, info, 'p1-01-home')
})

test('each rail item changes the URL and opens a page with its own heading', async ({ page }, info) => {
  await slowHome(page)
  await page.goto('/settings')
  for (const item of RAIL) {
    await mainMenu(page).getByRole('link', { name: linkName(item.label) }).click()
    await expect(page).toHaveURL(new RegExp(`${item.path === '/' ? '/$' : `${item.path}$`}`))
    await expect(heading(page)).toHaveText(item.heading)
    await loaded(page)
    await expect(heading(page), 'a page change puts focus on the new heading, and it is still there once the page has loaded').toBeFocused()
    await expect(mainMenu(page).getByRole('link', { name: linkName(item.label) })).toHaveAttribute('aria-current', 'page')
    await shot(page, info, `p1-02-rail-${item.label.toLowerCase().replaceAll(' ', '-')}`)
  }
})

test('Back and Forward walk across three pages', async ({ page }) => {
  await page.goto('/')
  await mainMenu(page).getByRole('link', { name: linkName('Workflows') }).click()
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(heading(page)).toHaveText('Settings')
  await page.goBack()
  await expect(page).toHaveURL(/\/workflows$/)
  await expect(heading(page)).toHaveText('Workflows')
  await page.goBack()
  await expect(page).toHaveURL(/\/$/)
  await expect(heading(page)).toHaveText(HOME_ALICE)
  await page.goForward()
  await expect(heading(page)).toHaveText('Workflows')
  await page.goForward()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(heading(page)).toHaveText('Settings')
})

test('Settings at the rail’s foot opens Settings, and a path that does not exist says so', async ({ page }, info) => {
  await page.goto('/')
  await mainMenu(page).getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(heading(page)).toHaveText('Settings')
  await expect(mainMenu(page).getByRole('link', { name: 'Settings', exact: true })).toHaveAttribute('aria-current', 'page')

  await page.goto('/nowhere')
  await expect(heading(page)).toHaveText('Page not found')
  await shot(page, info, 'p1-03-not-found')
  await page.getByRole('link', { name: 'Go to Home' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(heading(page)).toHaveText(HOME_ALICE)
})

test('Teams opens a dialog, Escape closes it, and focus goes back to the Teams button', async ({ page }, info) => {
  await page.goto('/')
  const teams = page.getByRole('button', { name: /^Teams, practice copy/ })
  await teams.click()
  const dialog = page.getByRole('dialog', { name: 'Teams, practice copy' })
  await expect(dialog).toContainText('Microsoft Teams')
  await expect(dialog).toContainText('Practice copy. Nothing reaches the real Teams.')
  await expect(dialog.getByRole('button', { name: 'Close Teams' })).toBeFocused()
  await shot(page, info, 'p1-04-teams')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(teams).toBeFocused()
})

test('Teams closes with its Close button, or with a click outside it, and focus goes back to the Teams button', async ({ page }) => {
  await page.goto('/')
  const teams = page.getByRole('button', { name: /^Teams, practice copy/ })
  const dialog = page.getByRole('dialog', { name: 'Teams, practice copy' })
  await teams.click()
  await expect(dialog.getByRole('button', { name: 'Close Teams' })).toHaveText('Close')
  await dialog.getByRole('button', { name: 'Close Teams' }).click()
  await expect(dialog).toBeHidden()
  await expect(teams).toBeFocused()

  await teams.click()
  await expect(dialog).toBeVisible()
  await page.mouse.click(30, 300)
  await expect(dialog).toBeHidden()
  await expect(teams).toBeFocused()
})

test('Tab stays inside the open Teams drawer', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Teams, practice copy' })
  await expect(dialog.getByRole('button', { name: 'Close Teams' })).toBeFocused()
  for (let press = 0; press < 12; press += 1) {
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate((node) => node.contains(document.activeElement)), `focus after ${String(press + 1)} Tab presses`).toBe(true)
  }
})

test('Teams pressed before the signed-in person is known still puts focus on Close', async ({ page }) => {
  await page.route('**/api/v1/me', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Teams, practice copy' })
  await expect(dialog).toContainText('Microsoft Teams')
  await expect(dialog.getByRole('button', { name: 'Close Teams' })).toBeFocused()
})

test('Test controls act as Bob, and Bob can open Settings', async ({ page }, info) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Test controls' }).click()
  const panel = page.getByRole('region', { name: 'Test controls' })
  await expect(panel).toContainText('Only on a practice stack. Real sign-in hides this.')
  await expect(panel.getByRole('button', { name: 'Alice' })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'Bob' }).click()
  await expect(panel.getByRole('button', { name: 'Bob' })).toHaveAttribute('aria-pressed', 'true')
  const rail = mainMenu(page)
  await expect(rail).toContainText('Bob')
  await expect(rail).toContainText('Approver')
  await expect(rail).not.toContainText('Operator')
  await expect(page.getByRole('main').getByText(GREETING('Bob'))).toBeVisible()
  await shot(page, info, 'p1-05-acting-as-bob')

  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(heading(page)).toHaveText('Settings')
  await expect(page.getByRole('main')).toContainText('Only Operators change settings.')
  await shot(page, info, 'p1-06-settings-approver')
})

test('Tab reaches every rail control with a visible focus ring, and the skip link moves focus to the heading', async ({ page }, info) => {
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  await loaded(page)
  const walk = await walkTabs(page)
  const labels = walk.stops.map((stop) => stop.label)
  expect(labels[0], `the skip link is the first stop; stops: ${labels.join(', ')}`).toBe('Skip to main content')
  for (const name of ['Home', 'Workflows', 'Teams, practice copy', 'Settings', 'Test controls']) {
    expect(labels.filter((label) => label.includes(name)).length, `Tab reaches ${name}; stops: ${labels.join(', ')}`).toBeGreaterThan(0)
  }
  expect(walk.unreached, 'controls Tab never reached').toEqual([])
  expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing or the same as at rest').toEqual([])
  expect(outOfVisualOrder(walk.stops), 'Tab moves that go against the visual order').toEqual([])

  await page.reload()
  await expect(heading(page)).toBeVisible()
  await page.keyboard.press('Tab')
  const skip = page.getByRole('button', { name: 'Skip to main content' })
  await expect(skip).toBeFocused()
  await shot(page, info, 'p1-07-skip-link')
  await page.keyboard.press('Enter')
  await expect(heading(page)).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(mainMenu(page).getByRole('link', { name: linkName('Home') }), 'Tab goes on from the heading, not back to the rail').not.toBeFocused()
})

for (const [size, options] of [
  ['desktop', {}],
  ['phone', { phone: true }],
] as const) {
  test(`WCAG 2.2 AA: no violations on every page at ${size} width`, async ({ browser }, info) => {
    const context = await openContext(browser, options)
    const page = await context.newPage()
    for (const item of PAGES) {
      await page.goto(item.path)
      await expect(heading(page)).toBeVisible()
      await expectAccessible(page, path.join(OUT, 'axe'), `${item.label.toLowerCase().replaceAll(' ', '-')}-${size}`)
    }
    await page.goto('/')
    await page.getByRole('button', { name: 'Test controls' }).click()
    await expect(page.getByRole('region', { name: 'Test controls' })).toBeVisible()
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `home-test-controls-${size}`)
    await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `home-teams-${size}`)
    await shot(page, info, `p1-08-teams-${size}`)
    await context.close()
  })
}

test('at 390 px wide the page does not scroll sideways, and every rail item can be reached', async ({ browser }, info) => {
  const context = await openContext(browser, { phone: true })
  const page = await context.newPage()
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  const bar = mainMenu(page)
  await expect(railItems(page)).toHaveText([linkText('Home'), linkText('Workflows')])
  const barBox = await bar.boundingBox()
  expect(barBox?.y ?? -1, 'at 390 px the rail is a bar across the top, with no bar above it').toBeLessThanOrEqual(1)
  expect(barBox?.height ?? 999, 'at 390 px the rail stays on one row').toBeLessThanOrEqual(70)
  for (const control of [bar.getByRole('button', { name: /^Teams, practice copy/ }), bar.getByRole('link', { name: 'Settings', exact: true })]) {
    const box = await control.boundingBox()
    expect((box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= 390, 'the rail’s foot fits within 390 px').toBe(true)
  }
  for (const [label, to, words] of [
    ['Workflows', /\/workflows$/, 'Workflows'],
    ['Home', /\/$/, HOME_ALICE],
  ] as const) {
    const tab = bar.getByRole('link', { name: linkName(label) })
    const box = await tab.boundingBox()
    expect(box, `${label} is on the screen`).not.toBeNull()
    expect((box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= 390, `${label} fits within 390 px`).toBe(true)
    await tab.click()
    await expect(page).toHaveURL(to)
    await expect(heading(page)).toHaveText(words)
    await expect(tab).toHaveAttribute('aria-current', 'page')
    const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
    expect(widths.scroll, `${label}: no sideways scroll`).toBeLessThanOrEqual(widths.client)
  }
  await expect(bar.getByRole('img', { name: 'AI Workflow Builder' })).toBeVisible()
  await shot(page, info, 'p1-09-phone')
  await context.close()
})

test('WCAG 2.2 AA: no violations on every page at 860 px, where the rail is a bar across the top', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 860, height: 844 }, locale: 'en-SG', timezoneId: 'Asia/Singapore' })
  const page = await context.newPage()
  for (const item of PAGES) {
    await page.goto(item.path)
    await expect(heading(page)).toBeVisible()
    await expectAccessible(page, path.join(OUT, 'axe'), `${item.label.toLowerCase().replaceAll(' ', '-')}-860`)
  }
  await context.close()
})

test('wider than 860 px the rail is a column on the left, and at 860 px it becomes a bar across the top', async ({ browser }) => {
  for (const [width, column] of [
    [1280, true],
    [861, true],
    [860, false],
  ] as const) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, locale: 'en-SG', timezoneId: 'Asia/Singapore' })
    const page = await context.newPage()
    await page.goto('/')
    await expect(heading(page)).toBeVisible()
    const links = await railItems(page).evaluateAll((all) => all.map((a) => a.getBoundingClientRect()).map((r) => ({ x: r.x, y: r.y })))
    const sameColumn = new Set(links.map((l) => Math.round(l.x))).size === 1
    const sameRow = new Set(links.map((l) => Math.round(l.y))).size === 1
    expect({ width, column: sameColumn && !sameRow, bar: sameRow && !sameColumn }).toEqual({ width, column, bar: !column })
    const room = await page.evaluate(() => document.documentElement.clientWidth)
    const filled = (await page.getByRole('main').boundingBox())?.width ?? 0
    expect(filled, `at ${String(width)} px the page fills the window beside the rail, or under the bar`).toBeGreaterThanOrEqual(room - (column ? 92 : 0) - 1)
    await context.close()
  }
})

test('at 390 px the rail stays one row that fits, with Home at 12 or more and Teams at 3', async ({ browser }) => {
  const context = await openContext(browser, { phone: true })
  const page = await context.newPage()
  await page.route('**/api/v1/home', async (route) => {
    const response = await route.fetch()
    const home = (await response.json()) as Record<string, unknown>
    await route.fulfill({ response, json: { ...home, approvals_total: 12 } })
  })
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  const bar = mainMenu(page)
  await expect(bar.getByRole('link', { name: /^Home, \d{2,} things need you/ })).toBeVisible()
  // Teams' own count comes from the approvals it polls, so the badge is drawn by hand to size the bar.
  await bar.getByRole('button', { name: /^Teams, practice copy/ }).evaluate((button) => {
    const badge = document.createElement('span')
    badge.textContent = '3'
    badge.className = button.querySelector('span:last-child')?.className ?? ''
    button.append(badge)
  })
  const box = await bar.boundingBox()
  expect(box?.height ?? 999, 'the bar stays on one row').toBeLessThanOrEqual(70)
  const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  expect(widths.scroll, 'no sideways scroll').toBeLessThanOrEqual(widths.client)
  for (const control of [bar.getByRole('link', { name: 'Settings', exact: true }), bar.getByRole('button', { name: /Alice/ })]) {
    const at = await control.boundingBox()
    expect((at?.x ?? -1) >= 0 && (at?.x ?? 0) + (at?.width ?? 0) <= 390, 'the gear and the person stay on the screen').toBe(true)
  }
  await context.close()
})
