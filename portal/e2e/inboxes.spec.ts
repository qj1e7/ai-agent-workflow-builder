import { advanceUntil, openFrozen } from './support/clock'
import { lineEnded } from './support/flows'
import { goTo } from './support/people'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the Teams inbox and the mock Jira show what the live run did', async ({ page }, info) => {
  test.setTimeout(150_000)
  await openFrozen(page, '/')
  await advanceUntil(page, lineEnded(page, 'done'), { stepMs: 1_000 })

  await goTo(page, 'Teams')
  await expect(page.getByRole('heading', { name: 'Teams' })).toBeVisible()
  await expect(
    page.getByText(/needs an Approver\. 2 new releases: 1\.2\.16, 1\.2\.15\. It would create a Jira ticket/).first(),
    'the message carries what the agents found',
  ).toBeVisible()
  const cards = page.getByRole('article')
  await expect(cards, 'one card for the declined run and one for the live run').toHaveCount(2)
  await expect(cards.filter({ hasText: 'Declined by Bob' }), 'the declined run says who declined').toHaveCount(1)
  await expect(cards.filter({ hasText: 'Approved by Bob' }), 'the live run says who approved').toHaveCount(1)
  await expect(cards.first().getByText(/^Started by Alice, /), 'each card names its run').toBeVisible()
  await record(page, info, 'teams-inbox')

  await goTo(page, 'Jira')
  await expect(page.getByText('MOCK-142').first()).toBeVisible()
  await record(page, info, 'jira-tickets')
})
