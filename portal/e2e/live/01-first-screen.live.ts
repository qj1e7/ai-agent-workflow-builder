import type { Page } from '@playwright/test'
import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { outOfVisualOrder, walkTabs, withoutVisibleFocus } from '../support/keyboard'
import { expect, test } from './support/test'
import { openContext, OUT, shot } from './support/ui'

const GREETING = (name: string) => new RegExp(`^Good (morning|afternoon|evening), ${name}$`)

const MENU = [
  { label: 'Home', path: '/', heading: GREETING('Alice'), built: false },
  { label: 'Workflows', path: '/workflows', heading: 'Workflows', built: false },
  { label: 'Software watchlist', path: '/software', heading: 'Software watchlist', built: false },
  { label: 'Agent library', path: '/agents', heading: 'Agent library', built: true },
] as const

const PAGES = [...MENU.map(({ path: to, label }) => ({ label, path: to })), { label: 'Settings', path: '/settings' }]

/** Axe reads colours as they are drawn, so it waits for a panel's opening animation to end. */
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().length === 0)

const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Main' })
const heading = (page: Page) => page.getByRole('heading', { level: 1 })

test('Home greets the signed-in person and the menu reads Home, Workflows, Software watchlist, Agent library', async ({ page }, info) => {
  await page.goto('/')
  await expect(heading(page)).toHaveText(GREETING('Alice'))
  await expect(page.getByRole('banner')).toContainText('Alice')
  await expect(page.getByRole('banner')).toContainText('Operator and Approver')
  await expect(mainMenu(page).getByRole('link')).toHaveText(MENU.map((item) => item.label))
  await expect(mainMenu(page).getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('link', { name: 'New workflow' })).toHaveCount(0)
  await expect(page).toHaveTitle(/^Good (morning|afternoon|evening), Alice · AI Workflow Builder$/)
  await shot(page, info, 'p1-01-home')
})

test('each menu item changes the URL and opens a page with its own heading', async ({ page }, info) => {
  await page.goto('/settings')
  for (const item of MENU) {
    await mainMenu(page).getByRole('link', { name: item.label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${item.path === '/' ? '/$' : `${item.path}$`}`))
    await expect(heading(page)).toHaveText(item.heading)
    await expect(heading(page), 'a page change puts focus on the new heading').toBeFocused()
    await expect(mainMenu(page).getByRole('link', { name: item.label, exact: true })).toHaveAttribute('aria-current', 'page')
    if (!item.built) await expect(page.getByRole('main')).toContainText('This page is not built yet.')
    await shot(page, info, `p1-02-menu-${item.label.toLowerCase().replaceAll(' ', '-')}`)
  }
})

test('Back and Forward walk across three pages', async ({ page }) => {
  await page.goto('/')
  await mainMenu(page).getByRole('link', { name: 'Workflows' }).click()
  await mainMenu(page).getByRole('link', { name: 'Agent library' }).click()
  await expect(heading(page)).toHaveText('Agent library')
  await page.goBack()
  await expect(page).toHaveURL(/\/workflows$/)
  await expect(heading(page)).toHaveText('Workflows')
  await page.goBack()
  await expect(page).toHaveURL(/\/$/)
  await expect(heading(page)).toHaveText(GREETING('Alice'))
  await page.goForward()
  await expect(heading(page)).toHaveText('Workflows')
  await page.goForward()
  await expect(page).toHaveURL(/\/agents$/)
  await expect(heading(page)).toHaveText('Agent library')
})

test('the Settings gear opens Settings, and a path that does not exist says so', async ({ page }, info) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(heading(page)).toHaveText('Settings')
  await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveAttribute('aria-current', 'page')

  await page.goto('/nowhere')
  await expect(heading(page)).toHaveText('Page not found')
  await shot(page, info, 'p1-03-not-found')
  await page.getByRole('link', { name: 'Go to Home' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(heading(page)).toHaveText(GREETING('Alice'))
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

test('Test controls act as Bob, and Bob can open Settings', async ({ page }, info) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Test controls' }).click()
  const panel = page.getByRole('region', { name: 'Test controls' })
  await expect(panel).toContainText('Only on a practice stack. Real sign-in hides this.')
  await expect(panel.getByRole('button', { name: 'Alice' })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'Bob' }).click()
  await expect(panel.getByRole('button', { name: 'Bob' })).toHaveAttribute('aria-pressed', 'true')
  const header = page.getByRole('banner')
  await expect(header).toContainText('Bob')
  await expect(header).toContainText('Approver')
  await expect(header).not.toContainText('Operator')
  await expect(heading(page)).toHaveText(GREETING('Bob'))
  await shot(page, info, 'p1-05-acting-as-bob')

  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(heading(page)).toHaveText('Settings')
  await expect(page.getByRole('main')).toContainText('Only Operators change settings.')
  await shot(page, info, 'p1-06-settings-approver')
})

test('Tab reaches every header control with a visible focus ring, and the skip link moves focus to the heading', async ({ page }, info) => {
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  const walk = await walkTabs(page)
  const labels = walk.stops.map((stop) => stop.label)
  expect(labels[0], `the skip link is the first stop; stops: ${labels.join(', ')}`).toBe('Skip to main content')
  for (const name of ['AI Workflow Builder', 'Home', 'Workflows', 'Software watchlist', 'Agent library', 'Teams, practice copy', 'Settings', 'Test controls']) {
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
  await expect(page.getByRole('link', { name: 'AI Workflow Builder' }), 'Tab goes on from the heading, not back to the header').not.toBeFocused()
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

test('at 390 px wide the page does not scroll sideways, and every tab bar item can be reached', async ({ browser }, info) => {
  const context = await openContext(browser, { phone: true })
  const page = await context.newPage()
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  const bar = mainMenu(page)
  await expect(bar.getByRole('link')).toHaveText(['Home', 'Workflows', 'Watchlist', 'Agents'])
  for (const [label, to, words] of [
    ['Workflows', /\/workflows$/, 'Workflows'],
    ['Watchlist', /\/software$/, 'Software watchlist'],
    ['Agents', /\/agents$/, 'Agent library'],
    ['Home', /\/$/, GREETING('Alice')],
  ] as const) {
    const tab = bar.getByRole('link', { name: label })
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
  await expect(page.getByRole('banner')).toContainText('Workflow Builder')
  await shot(page, info, 'p1-09-phone')
  await context.close()
})
