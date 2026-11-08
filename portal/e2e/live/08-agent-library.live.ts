import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { expect, test } from './support/test'
import { signedInAs } from './support/settings'
import { OUT, shot } from './support/ui'

test('the Agent library opens on what it can do for software versioning, with no Not yet group', async ({ page }, info) => {
  await page.goto('/agents')
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
  await page.goto('/agents?tab=tools')
  await expect(page.getByRole('main').locator('[data-tool-id]').first()).toContainText(/Ready\.|Not working right now\.|Needs setup\./)
  await expect(page.getByRole('main')).not.toContainText('Draft')
  await page.getByRole('button', { name: /^Agents/ }).click()
  await expect(page).toHaveURL(/\/agents\?tab=agents$/)
  await expect(page.getByRole('link', { name: 'Planner' })).toBeVisible()
})

for (const phone of [false, true]) {
  test(`WCAG 2.2 AA: no violations on any Agent library tab at ${phone ? 'phone' : 'desktop'} width`, async ({ browser }) => {
    const alice = await signedInAs(browser, 'alice', { phone })
    const page = await alice.newPage()
    for (const tab of ['', '?tab=agents', '?tab=tools']) {
      await page.goto(`/agents${tab}`)
      await expect(page.getByRole('heading', { level: 1, name: 'Agent library' })).toBeVisible()
      await expect(page.getByRole('main').getByRole('status')).toHaveCount(0)
      await expectAccessible(page, path.join(OUT, 'axe'), `agents${tab.replace(/\W/g, '-')}-${phone ? 'phone' : 'desktop'}`)
      const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
      expect(widths.scroll, `${tab}: no sideways scroll`).toBeLessThanOrEqual(widths.client)
    }
    await alice.close()
  })
}
