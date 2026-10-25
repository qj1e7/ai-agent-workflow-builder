import { advanceUntil, openFrozen } from './support/clock'
import { connectModelThenOpenBuilder, planTheExample, tracker, waitingForApprover } from './support/flows'
import { record } from './support/record'
import { expect, test } from './support/test'

const DRAFTED = 'No saved agent fits, so the Room lead drafted one.'

async function plan(page: import('@playwright/test').Page, task: string, ready: string): Promise<void> {
  await page.getByLabel('What should happen?').fill(task)
  await page.getByRole('button', { name: 'Plan it' }).click()
  await advanceUntil(page, page.getByText(ready))
}

test('the builder asks for an AI model, then the Room lead picks the Release checker and the Operator runs it', async ({ page }, info) => {
  await openFrozen(page, '/builder')
  await record(page, info, 'builder-empty')

  await page.getByRole('button', { name: 'Plan the example' }).click()
  await advanceUntil(page, page.getByText('Connect an AI model in Settings first.'))
  await expect(page.getByRole('link', { name: 'Open Settings' }), 'the message says where to go').toBeVisible()
  await record(page, info, 'builder-no-model')

  await connectModelThenOpenBuilder(page)
  await planTheExample(page)
  await expect(page.getByLabel('GitHub repository', { exact: true }), 'the Room lead found the repository').toHaveValue('langchain-ai/langgraph')
  await expect(page.getByLabel('Jira project', { exact: true }), 'it could not find the project').toHaveValue('')
  await expect(page.getByText('The Room lead could not find this in your task.')).toBeVisible()
  await record(page, info, 'builder-planned')

  await page.getByRole('button', { name: 'Save and run' }).click()
  await expect(page.getByText('Fill this in.'), 'the empty project is named, and focus goes to it').toBeVisible()
  await expect(page.getByLabel('Jira project', { exact: true })).toBeFocused()

  await page.getByLabel('Jira project', { exact: true }).fill('MOCK')
  await page.getByRole('button', { name: 'Save and run' }).click()
  await advanceUntil(page, waitingForApprover(page))
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  await expect(tracker(page).getByText('Release checker').first(), "the line is drawn from the use case's plan").toBeVisible()
  await expect(tracker(page).getByText('Approval gate').first(), 'with the gate and the write the plan names').toBeVisible()
  await expect(tracker(page).getByText('Nothing written yet').first()).toBeVisible()
})

test('a task with no saved agent opens a draft, the check guides the fix, and the saved agent runs from the library', async ({ page }, info) => {
  await openFrozen(page, '/builder')
  await connectModelThenOpenBuilder(page)
  await plan(page, 'Every Friday summarise what we finished and raise a ticket.', DRAFTED)
  await advanceUntil(page, page.getByText(/Add a Jira project detail/))
  await expect(page.getByText('Create a Jira ticket: one Approver must approve it first.'), 'the approvals come from the check').toBeVisible()
  await record(page, info, 'builder-drafted')

  await page.getByRole('button', { name: 'Save agent' }).click()
  await expect(page.getByText('Fix the points above first.'), 'a draft with problems is not saved').toBeVisible()

  await page.getByRole('button', { name: 'Add detail' }).click()
  await expect(page.getByLabel('Detail 1', { exact: true })).toBeFocused()
  await page.getByLabel('Detail 1', { exact: true }).fill('Jira project')
  await page.getByLabel('Kind of detail 1', { exact: true }).selectOption('jira_project')
  await page.getByLabel('Example for detail 1', { exact: true }).fill('MOCK')
  await advanceUntil(page, page.getByText('Ready to save.'))
  await page.getByRole('button', { name: 'Save agent' }).click()
  await advanceUntil(page, page.getByText('Saved Weekly finished work, version 1.'))
  await expect(page.getByLabel('Jira project', { exact: true }), 'the example fills the detail').toHaveValue('MOCK')
  await record(page, info, 'builder-saved')

  await page.getByRole('heading', { level: 2, name: 'Agent library' }).scrollIntoViewIfNeeded()
  await expect(page.getByRole('heading', { level: 3, name: /^Weekly finished work/ })).toBeVisible()
  await record(page, info, 'builder-library')

  await page.getByRole('button', { name: 'Run Weekly finished work' }).click()
  await page.getByRole('button', { name: 'Save and run' }).last().click()
  await advanceUntil(page, waitingForApprover(page))
})

test('a starter agent is copied, not changed, and the copy is saved as a new agent', async ({ page }) => {
  await openFrozen(page, '/builder')
  await connectModelThenOpenBuilder(page)
  await expect(page.getByRole('button', { name: 'Edit Release checker', exact: true }), 'a starter has no Edit').toHaveCount(0)
  await page.getByRole('button', { name: 'Copy and edit Release checker', exact: true }).click()
  await expect(page.getByRole('heading', { level: 2, name: "The Room lead's plan" })).toBeFocused()
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Release checker copy')
  await advanceUntil(page, page.getByText('Ready to save.'))
  await page.getByRole('button', { name: 'Save agent' }).click()
  await advanceUntil(page, page.getByText('Saved Release checker copy, version 1.'))
  await page.getByRole('heading', { level: 2, name: 'Agent library' }).scrollIntoViewIfNeeded()
  await page.getByRole('button', { name: 'Edit Release checker copy' }).click()
  await advanceUntil(page, page.getByText('Changing Release checker copy.'))
})

test('a task the tools cannot do says what is missing', async ({ page }, info) => {
  await openFrozen(page, '/builder')
  await connectModelThenOpenBuilder(page)
  await plan(page, 'Book a meeting room for Friday.', 'The Room lead cannot do this yet.')
  await expect(page.getByText('Calendar.')).toBeVisible()
  await record(page, info, 'builder-cannot')
})
