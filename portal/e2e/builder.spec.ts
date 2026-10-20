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
})
