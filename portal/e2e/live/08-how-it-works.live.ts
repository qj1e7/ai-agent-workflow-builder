import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { expect, test } from './support/test'
import { settingsTab, signedInAs } from './support/settings'
import { OUT, shot } from './support/ui'

const HOW = '/settings?tab=how'

test('How it works opens on what it can do for software versioning, with no Not yet group', async ({ page }, info) => {
  await page.goto('/settings')
  await settingsTab(page, 'How it works').click()
  await expect(page).toHaveURL(/\/settings\?tab=how$/)
  await expect(page.getByRole('button', { name: 'What it can do' })).toHaveAttribute('aria-pressed', 'true')
  const main = page.getByRole('main')
  await expect(main.getByRole('heading', { level: 2, name: /^I can/ })).toBeVisible()
  await expect(main).toContainText('Check software for new releases on GitHub')
  await expect(main).not.toContainText(/Read Jira tickets|Post messages in Teams|Not yet|can’t I do yet/)
  await expect(main.locator('details')).toHaveCount(0)
  await expect(main).not.toContainText(/\bPlanned\b/)
  await shot(page, info, 'n19-02-what-it-can-do')
})

test('the Tools tab gives each tool its health from the registry, and the Agents tab keeps its tiles', async ({ page }) => {
  await page.goto(`${HOW}&show=tools`)
  await expect(page.getByRole('main').locator('[data-tool-id]').first()).toContainText(/Ready\.|Not working right now\.|Needs setup\./)
  await expect(page.getByRole('main')).not.toContainText('Draft')
  await page.getByRole('button', { name: /^Agents/ }).click()
  await expect(page).toHaveURL(/\/settings\?tab=how&show=agents$/)
  await expect(page.getByRole('link', { name: 'Planner' })).toBeVisible()
})

// The old address redirects while the page loads, so the navigation is done once the server answers.
test('an agent opens from its tile, closes back to the tile, and the old Agent library address leads to it', async ({ page }) => {
  await page.goto(`${HOW}&show=agents`)
  await page.getByRole('link', { name: 'Planner' }).click()
  await expect(page).toHaveURL(/\/settings\?tab=how&show=agents&agent=planner$/)
  const dialog = page.getByRole('dialog', { name: 'Planner' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('link', { name: 'Planner' })).toBeFocused()

  await page.goto('/agents/planner', { waitUntil: 'commit' })
  await expect(page).toHaveURL(/\/settings\?tab=how&show=agents&agent=planner$/)
  await expect(page.getByRole('dialog', { name: 'Planner' })).toBeVisible()
  await page.goto('/agents?tab=tools', { waitUntil: 'commit' })
  await expect(page).toHaveURL(/\/settings\?tab=how&show=tools$/)
  await page.goto('/agents', { waitUntil: 'commit' })
  await expect(page).toHaveURL(/\/settings\?tab=how$/)
})

// CI run 43135325904: Escape hid the agent before the address went back a step, so the step back landed after the next page
// had opened and took the person back to the list. Here the step back is slow and the next page takes a second to come.
test('an agent closes by going back before it hides, so a page opened straight after stays open', async ({ page }) => {
  await page.addInitScript(() => {
    const go = history.go.bind(history)
    history.go = (delta?: number) => {
      setTimeout(() => go(delta), 300)
    }
  })
  await page.route('**/agents/planner', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1_000))
    await route.continue()
  })
  await page.goto(`${HOW}&show=agents`)
  await page.getByRole('link', { name: 'Planner' }).click()
  const dialog = page.getByRole('dialog', { name: 'Planner' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  expect(page.url(), 'once the agent is hidden, the address no longer names it').toMatch(/\/settings\?tab=how&show=agents$/)

  await page.goto('/agents/planner', { waitUntil: 'commit' })
  await expect(page).toHaveURL(/\/settings\?tab=how&show=agents&agent=planner$/)
  await expect(page.getByRole('dialog', { name: 'Planner' })).toBeVisible()
})

test('Close and a press outside the card each close an agent back to its tile', async ({ page }) => {
  await page.goto(`${HOW}&show=agents`)
  const dialog = page.getByRole('dialog', { name: 'Planner' })
  for (const how of ['Close', 'a press outside'] as const) {
    await page.getByRole('link', { name: 'Planner' }).click()
    await expect(dialog).toBeVisible()
    if (how === 'Close') await dialog.getByRole('button', { name: 'Close' }).last().click()
    else await page.mouse.click(5, 5)
    await expect(dialog, `${how} closes the agent`).toBeHidden()
    expect(page.url(), `${how} leaves the address on the list`).toMatch(/\/settings\?tab=how&show=agents$/)
    await expect(page.getByRole('link', { name: 'Planner' })).toBeFocused()
  }
})

test('an Approver who is not an Operator is not offered How it works, and the old address leads Home', async ({ browser }) => {
  const bob = await signedInAs(browser, 'bob')
  const page = await bob.newPage()
  await page.goto('/settings')
  await expect(settingsTab(page, 'Connections')).toBeVisible()
  await expect(page.getByRole('group', { name: 'Settings sections' }).getByRole('button', { name: 'How it works' })).toHaveCount(0)
  await page.goto(HOW)
  await expect(settingsTab(page, 'Connections')).toHaveAttribute('aria-pressed', 'true')
  await page.goto('/agents', { waitUntil: 'commit' })
  await expect(page).toHaveURL(/\/$/)
  await bob.close()
})

for (const phone of [false, true]) {
  test(`WCAG 2.2 AA: no violations on any How it works tab at ${phone ? 'phone' : 'desktop'} width`, async ({ browser }) => {
    const alice = await signedInAs(browser, 'alice', { phone })
    const page = await alice.newPage()
    for (const tab of ['', '&show=agents', '&show=tools']) {
      await page.goto(`${HOW}${tab}`)
      await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
      await expect(page.getByRole('main').getByRole('status')).toHaveCount(0)
      await expectAccessible(page, path.join(OUT, 'axe'), `how-it-works${tab.replace(/\W/g, '-')}-${phone ? 'phone' : 'desktop'}`)
      const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
      expect(widths.scroll, `${tab}: no sideways scroll`).toBeLessThanOrEqual(widths.client)
    }
    await alice.close()
  })
}
