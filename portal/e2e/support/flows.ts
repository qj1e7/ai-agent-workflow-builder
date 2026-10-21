import type { Page } from '@playwright/test'
import { advanceUntil } from './clock'

/** The Tracker's status region: the headline and the subline, read out together. */
const status = (page: Page) => page.locator('[role="status"][aria-atomic="true"]')

export const headline = (page: Page) => status(page).getByRole('heading', { level: 2 })

export const waitingForApprover = (page: Page) => status(page).getByRole('heading', { name: /^Waiting for (an Approver|your approval)$/ })

export const tracker = (page: Page) => page.locator('section[data-at-head]')

/** How a run ends on the Tracker's line. */
const ENDS = {
  done: 'li[data-stop="done"][data-state="done"]',
  declined: 'li[data-gate="declined"]',
  stopped: 'li[data-stop][data-state="failed"]',
} as const

export const lineEnded = (page: Page, end: keyof typeof ENDS) => page.locator(ENDS[end])

/** Plans the example task, saves it, runs it, and stops at the approval pause of the new run, which waits for a real decision. */
export async function startRunFromBuilder(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Plan the example' }).click()
  await advanceUntil(page, page.getByRole('heading', { name: 'Matched your words' }))
  await page.getByRole('button', { name: 'Save use case' }).click()
  await advanceUntil(page, page.getByText(/^Saved .+, version 1/))
  await page.getByRole('button', { name: 'Run now' }).first().click()
  await advanceUntil(page, waitingForApprover(page))
}
