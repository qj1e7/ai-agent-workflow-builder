import { advance, advanceUntil, openFrozen } from './support/clock'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the overview shows each stage of the live success run', async ({ page }, info) => {
  await openFrozen(page, '/')
  await record(page, info, 'overview-load')

  await advance(page, 4_000)
  await record(page, info, 'overview-mid-run')

  await advanceUntil(page, page.getByText('Waiting for an Approver', { exact: true }).first())
  await record(page, info, 'overview-pause')

  await advanceUntil(page, page.getByText('Approved, being written'))
  await record(page, info, 'overview-writing')

  await advanceUntil(page, page.getByText('Finished', { exact: true }))
  await expect(page.getByText('Written as MOCK-142').first()).toBeVisible()
  await record(page, info, 'overview-success')

  await page.locator('#earlier-title').evaluate((heading) => heading.scrollIntoView({ block: 'start' }))
  await page.waitForTimeout(600)
  await record(page, info, 'overview-earlier-runs', { viewportOnly: true })
})
