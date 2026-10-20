import { advanceUntil, openFrozen } from './support/clock'
import { transportSays } from './support/flows'
import { goTo } from './support/people'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the Teams inbox and the mock Jira show what the live run did', async ({ page }, info) => {
  await openFrozen(page, '/')
  await advanceUntil(page, transportSays(page, 'Done'))

  await goTo(page, 'Teams')
  await expect(page.getByRole('heading', { name: 'Teams' })).toBeVisible()
  await expect(page.getByText(/Approval needed/).first()).toBeVisible()
  await record(page, info, 'teams-inbox')

  await goTo(page, 'Jira')
  await expect(page.getByText('MOCK-142').first()).toBeVisible()
  await record(page, info, 'jira-tickets')
})
