import { advance, advanceUntil, openFrozen } from './support/clock'
import { transportSays, waitingForApprover } from './support/flows'
import { expectFitsTheFold } from './support/fold'
import { record } from './support/record'
import { expect, test } from './support/test'

test('the success run page shows the run from work to written ticket', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JB8')
  if (info.project.name === 'desktop') await expectFitsTheFold(page)
  await advance(page, 4_000)
  await record(page, info, 'run-mid-run')

  await advanceUntil(page, waitingForApprover(page))
  await record(page, info, 'run-pause')

  await advanceUntil(page, transportSays(page, 'Done'))
  await expect(page.getByText('Written as MOCK-142').first()).toBeVisible()
  await expect(page.getByRole('log').locator('li').last(), 'the latest Minutes entry is marked').toHaveAttribute('aria-current', 'true')
  await record(page, info, 'run-success')

  const slider = page.getByRole('slider', { name: 'Position in the run' })
  await slider.focus()
  await page.keyboard.press('Home')
  for (let press = 0; press < 6; press += 1) await page.keyboard.press('ArrowRight')
  await advance(page, 300, 800)
  await expect(slider, 'the scrubber moved off the end of the run').not.toHaveValue((await slider.getAttribute('max')) ?? '')
  await record(page, info, 'run-scrubbed-back')

  await page.getByRole('button', { name: 'Technical details' }).click()
  await advance(page, 300, 600)
  await expect(page.getByRole('button', { name: 'Technical details' })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('log').getByText(/^seq \d+$/).first(), 'the technical entries show their sequence numbers').toBeVisible()
  await record(page, info, 'run-technical-details')
})

test('the failed run page explains the stop and recovers after Retry run', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JB9')
  await advanceUntil(page, page.getByRole('heading', { name: 'AI troubleshooter' }))
  await expect(page.getByRole('button', { name: 'Retry run' })).toBeVisible()
  await record(page, info, 'run-failure')

  await page.getByRole('button', { name: 'Retry run' }).click()
  await advanceUntil(page, waitingForApprover(page))
  await expect(page.getByText('Attempt 2').first()).toBeVisible()
  await record(page, info, 'run-after-retry')
})

test('the rejected run page shows that nothing was written', async ({ page }, info) => {
  await openFrozen(page, '/runs/run_01JBA')
  await advanceUntil(page, transportSays(page, 'Declined'))
  await expect(page.getByText('Declined', { exact: true }).first()).toBeVisible()
  await record(page, info, 'run-rejected')
})
