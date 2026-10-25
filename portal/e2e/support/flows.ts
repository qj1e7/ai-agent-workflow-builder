import type { Page } from '@playwright/test'
import { advanceUntil } from './clock'

/** The Tracker's status region: the headline and the subline, read out together. */
export const status = (page: Page) => page.locator('[role="status"][aria-atomic="true"]')

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

/** Connects the demo AI model in Settings and comes back to the Builder, by links, so the demo platform keeps its state. */
export async function connectModelThenOpenBuilder(page: Page): Promise<void> {
  await page.getByRole('link', { name: 'Settings', exact: true }).first().click()
  await advanceUntil(page, page.getByLabel('Key', { exact: true }))
  await page.getByLabel('Key', { exact: true }).fill('sk-example-key-not-real-x7')
  await page.getByRole('button', { name: 'Connect' }).click()
  await advanceUntil(page, page.getByText(/^Connected to AI Singapore gateway/))
  await page.getByRole('button', { name: 'Test and save' }).click()
  await advanceUntil(page, page.getByText(/^Saved\. The model answered/))
  await page.getByRole('link', { name: 'Builder', exact: true }).first().click()
  await advanceUntil(page, page.getByRole('heading', { level: 1, name: 'Builder' }))
}

/** Plans the example task, which picks the Release checker and leaves the Jira project to fill in. */
export async function planTheExample(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Plan the example' }).click()
  await advanceUntil(page, page.getByText('The Room lead picked Release checker.'))
}

/** Connects the model, plans the example, fills in the Jira project and runs it. Stops at the approval pause of the new run, which waits for a real decision. */
export async function startRunFromBuilder(page: Page): Promise<void> {
  await connectModelThenOpenBuilder(page)
  await planTheExample(page)
  await page.getByLabel('Jira project', { exact: true }).fill('MOCK')
  await page.getByRole('button', { name: 'Save and run' }).click()
  await advanceUntil(page, waitingForApprover(page))
}
