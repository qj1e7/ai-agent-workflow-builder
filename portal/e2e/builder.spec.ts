import { advanceUntil, openFrozen } from './support/clock'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the builder plans a task and saves it as a use case', async ({ page }, info) => {
  await openFrozen(page, '/builder')
  await record(page, info, 'builder-empty')

  await page.getByRole('button', { name: 'Use the example' }).click()
  await page.getByRole('button', { name: 'Plan it' }).click()
  await advanceUntil(page, page.getByRole('heading', { name: 'Matched your words' }))
  await record(page, info, 'builder-planned')

  await page.getByRole('button', { name: 'Save use case' }).click()
  await advanceUntil(page, page.getByText(/^Saved .+, version 1/))
  await expect(page.getByRole('button', { name: 'Run now' }).first()).toBeVisible()
  await record(page, info, 'builder-saved')

  await expect(page.getByLabel(/regular expression/i), 'the release tag pattern is not a field to fill in').toHaveCount(0)
  await page.getByText('Technical details').click()
  const fixed = page.locator('dt', { hasText: /regular expression/i })
  await expect(fixed, 'the pattern is listed under technical details').toBeVisible()
  await expect(fixed.locator('xpath=following-sibling::dd[1]//code'), 'with its value, read only').toHaveText('^\\d+\\.\\d+\\.\\d+$')
})
