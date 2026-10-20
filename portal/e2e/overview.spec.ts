import { advance, advanceUntil, openFrozen } from './support/clock'
import { transportSays } from './support/flows'
import { expectEndsAboveTheFold, expectFitsTheFold } from './support/fold'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the overview shows each stage of the live success run', async ({ page }, info) => {
  await openFrozen(page, '/')
  if (info.project.name === 'desktop') await expectFitsTheFold(page, 'earlier-title')
  await record(page, info, 'overview-load')

  await advance(page, 4_000)
  await record(page, info, 'overview-mid-run')

  await advanceUntil(page, page.getByText('Waiting for an Approver', { exact: true }).first())
  const soFar = page.getByRole('region', { name: 'So far' }).locator('li')
  if (info.project.name === 'desktop') await expectEndsAboveTheFold(soFar.last(), 'the latest So far entry at the pause')
  await record(page, info, 'overview-pause')

  await advanceUntil(page, page.locator('[data-ticket="approved"]'))
  await record(page, info, 'overview-writing')

  await advanceUntil(page, transportSays(page, 'Done'))
  await expect(page.getByText('Written as MOCK-142').first()).toBeVisible()
  const times = await soFar.locator('time').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('datetime') ?? ''))
  expect(times, 'So far reads oldest first').toEqual([...times].sort())
  await expect(soFar.last(), 'the latest So far entry is marked').toHaveAttribute('aria-current', 'true')
  await record(page, info, 'overview-success')

  await page.locator('#earlier-title').evaluate((heading) => heading.scrollIntoView({ block: 'start' }))
  await page.waitForTimeout(600)
  await record(page, info, 'overview-earlier-runs', { viewportOnly: true })
})
