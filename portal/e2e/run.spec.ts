import { advance, advanceUntil, openFrozen } from './support/clock'
import { headline, lineEnded, status, tracker, waitingForApprover } from './support/flows'
import { expectFitsTheFold } from './support/fold'
import { record } from './support/record'
import { isDesktop } from './support/states'
import { expect, test } from './support/test'

test('the success run page shows the run from work to written ticket', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JB8')
  if (isDesktop(info.project.name)) await expectFitsTheFold(page)
  await advance(page, 4_000)
  await record(page, info, 'run-mid-run')

  await advanceUntil(page, waitingForApprover(page))
  await record(page, info, 'run-pause')

  await advanceUntil(page, lineEnded(page, 'done'))
  await expect(headline(page)).toHaveText('MOCK-142 is in Jira')
  await expect(page.getByRole('log').locator('li').last(), 'the latest Minutes entry is marked').toHaveAttribute('aria-current', 'true')
  await record(page, info, 'run-success')

  await page.getByRole('button', { name: 'Technical details' }).click()
  await advance(page, 300, 600)
  await expect(page.getByRole('button', { name: 'Technical details' })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('log').getByText(/^seq \d+$/).first(), 'the technical entries show their sequence numbers').toBeVisible()
  await record(page, info, 'run-technical-details')
})

test('Instant shows the newest state of a run at once', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JB8')
  await advance(page, 2_000)
  await advanceUntil(page, page.locator('section[data-at-head="false"]'))
  await expect(tracker(page), 'the view plays a beat behind the newest event').toHaveAttribute('data-speed', '1')
  await expect(status(page), 'a screen reader hears nothing old while the view plays behind').toHaveAttribute('aria-live', 'off')
  await expect(page.getByRole('log'), 'the Minutes are for reading, so they never repeat the status region').toHaveAttribute('aria-live', 'off')

  await page.getByRole('radio', { name: 'Instant' }).check()
  await expect(tracker(page), 'Instant lands on the newest event without moving the clock').toHaveAttribute('data-at-head', 'true')
  await expect(tracker(page)).toHaveAttribute('data-speed', 'instant')
  await expect(status(page), 'at the newest event the status region speaks').toHaveAttribute('aria-live', 'polite')
  await record(page, info, 'run-instant')
})

test('the failed run page explains the stop and recovers after Retry run', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JB9')
  const advice = page.getByRole('region', { name: 'AI troubleshooter advice' })
  await advanceUntil(page, advice)
  await expect(lineEnded(page, 'stopped'), 'the line breaks where the run stopped').toBeVisible()
  await expect(headline(page)).toHaveText('The run stopped')
  const retry = advice.getByRole('button', { name: 'Retry run' })
  await expect(retry).toBeVisible()
  await record(page, info, 'run-failure')

  await retry.click()
  await advanceUntil(page, waitingForApprover(page))
  await expect(tracker(page).getByText('Attempt 2', { exact: true }), 'the Tracker names the attempt').toBeVisible()
  await expect(advice, 'the advice goes once the run moves on').toHaveCount(0)
  await record(page, info, 'run-after-retry')
})

test('the rejected run page shows that nothing was written', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JBA')
  await advanceUntil(page, lineEnded(page, 'declined'))
  await expect(headline(page)).toHaveText('Declined by Bob')
  await record(page, info, 'run-rejected')
})
