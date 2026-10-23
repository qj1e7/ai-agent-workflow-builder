import { type Page } from '@playwright/test'
import { advance, advanceUntil, finishLoading, openFrozen } from './support/clock'
import { waitingForApprover } from './support/flows'
import { outOfVisualOrder, tabTo, walkTabs, withoutVisibleFocus } from './support/keyboard'
import { withoutKnown } from './support/known'
import { switchUser } from './support/people'
import { expect, test } from './support/test'

async function openApprovalAs(page: Page, user: string): Promise<void> {
  await openFrozen(page, '/')
  await advanceUntil(page, waitingForApprover(page))
  await page.getByRole('link', { name: 'Open the approval page' }).click()
  await page.getByRole('heading', { name: 'Approve a write to Jira' }).waitFor()
  await finishLoading(page)
  await switchUser(page, user)
}

async function expectGoodWalk(page: Page, scope: string): Promise<void> {
  const walk = await walkTabs(page)
  expect(walk.stops.length, 'Tab reached some interactive elements').toBeGreaterThan(3)
  expect(walk.unreached, 'visible interactive elements Tab never reached').toEqual([])
  expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing or the same as at rest').toEqual([])
  expect(withoutKnown('tab-order', scope, outOfVisualOrder(walk.stops)), 'Tab moves that go against the visual order').toEqual([])
}

test('Tab walks the overview in visual order with a visible focus ring', async ({ page }, info) => {
  await openFrozen(page, '/')
  await expectGoodWalk(page, `${info.project.name}/overview`)
})

test('Tab walks the approval page in visual order with a visible focus ring', async ({ page }, info) => {
  await openApprovalAs(page, 'Bob')
  await expect(page.getByRole('button', { name: /^Approve and write to/ })).toBeEnabled()
  await expectGoodWalk(page, `${info.project.name}/approval`)
})

test('the user switcher works with the keyboard alone', async ({ page }) => {
  await openFrozen(page, '/')
  const trigger = page.getByRole('button', { name: /Switch user/ })
  await tabTo(page, /Switch user/)
  await expect(trigger).toBeFocused()

  await page.keyboard.press('Enter')
  const menu = page.getByRole('menu', { name: 'Switch user' })
  await expect(menu, 'Enter opens the menu').toBeVisible()
  await expect(page.getByRole('menuitemradio', { name: /Alice/ }), 'focus starts on the signed-in user').toBeFocused()

  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('menuitemradio', { name: /Bob/ }), 'ArrowDown moves to the next user').toBeFocused()
  await page.keyboard.press('Enter')
  await expect(menu, 'choosing a user closes the menu').toBeHidden()
  await expect(trigger, 'the trigger shows the new user').toContainText('Bob')
  await expect(trigger, 'focus returns to the trigger').toBeFocused()

  await page.keyboard.press('ArrowDown')
  await expect(menu, 'ArrowDown opens the menu again').toBeVisible()
  await page.keyboard.press('Escape')
  await expect(menu, 'Escape closes the menu').toBeHidden()
  await expect(trigger, 'focus returns to the trigger after Escape').toBeFocused()
})

test('the transport pauses, restarts and scrubs with the keyboard alone', async ({ page }) => {
  await openFrozen(page, '/runs/run_01JB8')
  await advance(page, 6_000)
  const slider = page.getByRole('slider', { name: 'Position in the run' })
  const valueNow = async () => Number(await slider.inputValue())

  await tabTo(page, /^Pause$/)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Play', exact: true }), 'Enter on Pause turns it into Play').toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Pause', exact: true }), 'Enter on Play turns it back into Pause').toBeFocused()

  const before = await valueNow()
  expect(before, 'the run has moved on from the start').toBeGreaterThan(0)
  await tabTo(page, /^Restart from the beginning$/)
  await page.keyboard.press('Enter')
  await advance(page, 300, 800)
  await expect(slider, 'Restart puts the scrubber back at the start').toHaveValue('0')

  await tabTo(page, /^Position in the run$/)
  await expect(slider).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await advance(page, 300, 800)
  const forward = await valueNow()
  expect(forward, 'ArrowRight moves the scrubber forward').toBeGreaterThan(0)
  await page.keyboard.press('ArrowRight')
  await advance(page, 300, 800)
  expect(await valueNow(), 'a second ArrowRight moves it further').toBeGreaterThan(forward)
  await page.keyboard.press('ArrowLeft')
  await advance(page, 300, 800)
  expect(await valueNow(), 'ArrowLeft moves it back').toBeLessThan(await slider.evaluate((el) => Number((el as HTMLInputElement).max)))
  await page.keyboard.press('Home')
  await advance(page, 300, 800)
  expect(await valueNow(), 'Home goes to the first moment of the run').toBeLessThanOrEqual(forward)
})

test('an Approver approves with the keyboard alone', async ({ page }) => {
  await openApprovalAs(page, 'Bob')
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await tabTo(page, /^Approve and write to/)
  await expect(page.getByRole('button', { name: /^Approve and write to/ })).toBeFocused()
  await page.keyboard.press('Enter')
  await advanceUntil(page, page.getByText(/^Approved by Bob/))
  await expect(page.getByText(/^Approved by Bob/).first()).toBeVisible()
})
