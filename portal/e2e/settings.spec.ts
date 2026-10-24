import { advanceUntil, openFrozen } from './support/clock'
import { switchUser } from './support/people'
import { record } from './support/record'
import { expect, test } from './support/test'

test('an Operator connects a model, and a new address waits for another Approver', async ({ page }, info) => {
  await openFrozen(page, '/settings')
  await expect(page.getByText(/^No AI model is set/)).toBeVisible()
  await record(page, info, 'settings-empty')

  await page.getByLabel('Key', { exact: true }).fill('sk-example-key-not-real-x7')
  await page.getByRole('button', { name: 'Connect' }).click()
  await advanceUntil(page, page.getByText(/^Connected to AI Singapore gateway/))
  await expect(page.getByRole('radio', { name: /Claude Haiku 5\.5/ }), 'the fast model is picked for you').toBeChecked()
  await record(page, info, 'settings-connected')

  await page.getByRole('button', { name: 'Test and save' }).click()
  await advanceUntil(page, page.getByText(/^Saved\. The model answered/))
  await advanceUntil(page, page.getByText('Summaries are written by claude-haiku-5-5 (AI Singapore gateway).'))
  await expect(page.getByLabel('Saved key ending in x7'), 'the key is never shown again').toBeVisible()
  await record(page, info, 'settings-saved')

  await page.getByRole('radio', { name: /Another address/ }).check()
  await page.getByLabel('Address', { exact: true }).fill('https://ai-gateway.ncs.example/v1')
  await page.getByLabel('Key', { exact: true }).fill('ncs-example-key-not-real-q4')
  await page.getByRole('button', { name: 'Connect' }).click()
  await advanceUntil(page, page.getByText(/^Connected to ai-gateway\.ncs\.example/))
  await page.getByRole('button', { name: 'Test and save' }).click()
  await advanceUntil(page, page.getByText(/an Approver must confirm it before runs use it/))
  await advanceUntil(page, page.getByText('You entered this address, so another Approver must confirm it.'))
  await expect(page.getByText('Summaries are written by claude-haiku-5-5 (AI Singapore gateway).'), 'runs keep the old model').toBeVisible()
  await record(page, info, 'settings-pending-alice')

  await switchUser(page, 'Bob')
  const confirm = page.getByRole('button', { name: 'Confirm the address' })
  await expect(confirm).toBeVisible()
  await expect(page.getByRole('button', { name: 'Connect' }), 'an Approver sees the settings but cannot change them').toHaveCount(0)
  await record(page, info, 'settings-pending-bob')

  await confirm.click()
  await advanceUntil(page, page.getByText('Summaries are written by ncs-llm-small (ai-gateway.ncs.example).'))
  await expect(page.getByText('Bob confirmed ai-gateway.ncs.example. Runs now use ncs-llm-small.')).toBeVisible()
  await record(page, info, 'settings-confirmed')
})

test('a refused key and a slow model are explained in plain words, and nothing is saved', async ({ page }) => {
  await openFrozen(page, '/settings')
  await page.getByLabel('Key', { exact: true }).fill('short')
  await page.getByRole('button', { name: 'Connect' }).click()
  await advanceUntil(page, page.getByText('The address answered, but it refused this key. Check that you copied all of it.'))

  await page.getByRole('radio', { name: /Another address/ }).check()
  await page.getByLabel('Address', { exact: true }).fill('https://models.example/v1')
  await page.getByLabel('Key', { exact: true }).fill('sk-example-key-not-real-x7')
  await page.getByRole('button', { name: 'Connect' }).click()
  await advanceUntil(page, page.getByRole('radio', { name: /chat-large/ }))
  await page.getByRole('radio', { name: /chat-large/ }).check()
  await page.getByRole('button', { name: 'Test and save' }).click()
  await advanceUntil(page, page.getByText(/^The model answered in 11\.2 seconds/))
  await expect(page.getByText(/^No AI model is set/)).toBeVisible()
})

test('the gear in the header opens the settings', async ({ page }) => {
  await openFrozen(page, '/')
  await page.getByRole('link', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
})
