import type { Page } from '@playwright/test'
import { advanceUntil } from './clock'

export const waitingForApprover = (page: Page) => page.getByRole('heading', { name: /waiting for an Approver/ })

/** Plans the example task, saves it, runs it, and stops at the approval pause of the new run, which waits for a real decision. */
export async function startRunFromBuilder(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Use the example' }).click()
  await page.getByRole('button', { name: 'Plan it' }).click()
  await advanceUntil(page, page.getByRole('heading', { name: 'Matched your words' }))
  await page.getByRole('button', { name: 'Save use case' }).click()
  await advanceUntil(page, page.getByText(/^Saved .+, version 1/))
  await page.getByRole('button', { name: 'Run now' }).first().click()
  await advanceUntil(page, waitingForApprover(page))
}
