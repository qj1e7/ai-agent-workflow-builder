import { advanceUntil, openFrozen } from './support/clock'
import { transportSays } from './support/flows'
import { goTo } from './support/people'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the Teams inbox and the mock Jira show what the live run did', async ({ page }, info) => {
  // The live run plays its whole story before Done, about 25 s of page time, so this test needs more than the default budget.
  test.setTimeout(150_000)
  await openFrozen(page, '/')
  await advanceUntil(page, transportSays(page, 'Done'), { stepMs: 1_000 })

  await goTo(page, 'Teams')
  await expect(page.getByRole('heading', { name: 'Teams' })).toBeVisible()
  await expect(page.getByText(/Approval needed/).first()).toBeVisible()
  await record(page, info, 'teams-inbox')

  await goTo(page, 'Jira')
  await expect(page.getByText('MOCK-142').first()).toBeVisible()
  await record(page, info, 'jira-tickets')
})
