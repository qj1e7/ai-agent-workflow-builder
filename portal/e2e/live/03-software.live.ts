import { assertClean, watchPage } from '../support/test'
import { expect, test } from './support/test'
import { devContext, shot } from './support/ui'

test('alice adds software, presses Check now, and the row moves from Not checked yet to a status with the newest version', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice', [])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/software')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Software watchlist')
  await page.getByLabel('Name', { exact: true }).fill('FastAPI')
  await page.getByLabel('GitHub repository').fill('https://github.com/fastapi/fastapi')
  await page.getByLabel(/^Our version/).fill('0.115.0')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const row = page.locator('li[data-status]').filter({ hasText: 'FastAPI' })
  await expect(row).toContainText('Not checked yet')
  await shot(page, info, 'p6-03-added')

  await page.getByRole('button', { name: 'Check now' }).click()
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  const runId = page.url().split('/').at(-1) ?? ''
  await backend.waitForState(runId, ['awaiting_approval', 'succeeded'])

  await page.goto('/software')
  await expect(row).not.toContainText('Not checked yet', { timeout: 30_000 })
  await expect(row.locator('dl')).toContainText('Newest')
  await shot(page, info, 'p6-03-checked')
  assertClean(watch)
  await context.close()
})
