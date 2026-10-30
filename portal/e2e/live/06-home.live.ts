import path from 'node:path'
import type { Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

const needsYou = (page: Page) => page.getByRole('list', { name: 'Needs you' })
const itemOf = (page: Page, approvalId: string) => page.locator(`li[data-home-item="approval:${approvalId}"]`)
const waitingOnOthers = (page: Page) => page.getByRole('region', { name: 'Waiting on others' })

/** A value on window survives a client-side page change and is gone after a reload. */
async function markThisPage(page: Page): Promise<void> {
  await page.evaluate(() => {
    ;(window as unknown as { __homeNotReloaded: boolean }).__homeNotReloaded = true
  })
}

async function notReloaded(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __homeNotReloaded?: boolean }).__homeNotReloaded === true)
}

test('bob sees the run alice started at the top of Home, and its one button opens the run at the decision', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/')
  const first = needsYou(page).locator('li[data-home-item]').first()
  await expect(first).toHaveAttribute('data-home-item', `approval:${approvalId}`)
  await expect(first).toContainText(/1 ticket is waiting for your yes/)
  await expect(first.getByRole('link')).toHaveCount(1)
  await expect(first.getByRole('link', { name: 'Review and decide' })).toHaveAttribute('href', `/runs/${runId}`)
  await expect(page.getByRole('main').getByRole('button', { name: /^Approve/ }), 'nothing is decided on Home').toHaveCount(0)
  await shot(page, info, 'p11-06-bob-home')

  await first.getByRole('link', { name: 'Review and decide' }).click()
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
  await expect(page.locator('#decision'), 'the run page lands on the decision').toBeFocused()
  await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
  assertClean(watch)
  await context.close()
})

test('alice sees the run she started under Waiting on others, with no Approve button', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  await expect(waitingOnOthers(page).locator(`a[href="/runs/${runId}"]`)).toContainText('You started it')
  await expect(itemOf(page, approvalId)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Approve/ })).toHaveCount(0)
  await shot(page, info, 'p11-06-alice-home')
  await context.close()
})

test('bob approves on the run page, and the item has left Home when he comes back, without a reload', async ({ browser, backend }) => {
  const { approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(itemOf(page, approvalId)).toBeVisible()
  await markThisPage(page)
  await itemOf(page, approvalId).getByRole('link', { name: 'Review and decide' }).click()
  await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
  await expect(page.getByText('Approved. The platform is writing now.').or(page.getByRole('heading', { level: 1, name: /created in Jira/ }))).toBeVisible()
  await page.getByRole('navigation', { name: 'Main' }).filter({ visible: true }).getByRole('link', { name: 'Home' }).click()
  await expect(page.getByRole('heading', { level: 2, name: /Needs you/ })).toBeVisible()
  await expect(itemOf(page, approvalId)).toHaveCount(0)
  expect(await notReloaded(page), 'Home updated without a reload').toBe(true)
  await context.close()
})

test('a yes in the Teams panel takes the item off Home at once, without a reload', async ({ browser, backend }, info) => {
  const { approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(itemOf(page, approvalId)).toBeVisible()
  await markThisPage(page)
  await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
  const message = page.getByRole('dialog', { name: 'Teams, practice copy' }).locator(`li[data-approval-id="${approvalId}"]`)
  await message.scrollIntoViewIfNeeded()
  await message.getByRole('button', { name: 'Approve' }).click()
  await expect(message).toContainText('Approved by Bob')
  await page.keyboard.press('Escape')
  await expect(itemOf(page, approvalId)).toHaveCount(0, { timeout: 5_000 })
  expect(await notReloaded(page), 'Home updated without a reload').toBe(true)
  await shot(page, info, 'p11-06-after-teams-yes')
  await context.close()
})

for (const phone of [false, true]) {
  test(`Home passes WCAG 2.2 AA and does not scroll sideways at ${phone ? '390' : '1440'} px`, async ({ browser, backend }) => {
    await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob', { phone })
    const page = await context.newPage()
    await page.goto('/')
    await expect(needsYou(page)).toBeVisible()
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await expectAccessible(page, path.join(OUT, 'axe'), `home-bob-${phone ? 'phone' : 'desktop'}`)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await context.close()
  })
}
