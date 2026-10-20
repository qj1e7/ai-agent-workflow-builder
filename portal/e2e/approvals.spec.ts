import { advanceUntil, finishLoading, openFrozen } from './support/clock'
import { startRunFromBuilder } from './support/flows'
import { goTo, switchUser } from './support/people'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the approval page tells each person what they can do', async ({ page }, info) => {
  await openFrozen(page, '/builder')
  await startRunFromBuilder(page)

  await goTo(page, 'Approvals')
  await expect(page.getByRole('heading', { name: 'Approvals' })).toBeVisible()
  await record(page, info, 'approvals-list')

  await page.locator('a[href^="/approvals/apr_demo"]').click()
  await page.getByRole('heading', { name: 'Approve a write to Jira' }).waitFor()
  await finishLoading(page)
  await expect(page.getByText('You started this run, so another Approver must decide.')).toBeVisible()
  await record(page, info, 'approval-alice-refused')

  await switchUser(page, 'Carol')
  await expect(page.getByText('Only Approvers can decide this request.')).toBeVisible()
  await record(page, info, 'approval-carol-not-approver')

  await switchUser(page, 'Bob')
  const approve = page.getByRole('button', { name: /^Approve and write to/ })
  await expect(approve).toBeEnabled()
  await record(page, info, 'approval-bob-open')

  await approve.click()
  await advanceUntil(page, page.getByText(/^Approved by Bob/))
  await record(page, info, 'approval-approved')
})
