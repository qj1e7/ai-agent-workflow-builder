import { type Page } from '@playwright/test'
import { advance, advanceUntil, finishLoading, openFrozen } from './support/clock'
import { headline, tracker, waitingForApprover } from './support/flows'
import { outOfVisualOrder, tabTo, walkTabs, withoutVisibleFocus } from './support/keyboard'
import { withoutKnown } from './support/known'
import { goTo, switchUser } from './support/people'
import { expect, test } from './support/test'

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
  await openFrozen(page, '/')
  await advanceUntil(page, waitingForApprover(page))
  await switchUser(page, 'Bob')
  await goTo(page, 'Approvals')
  await page.getByRole('link', { name: 'Open the approval page' }).click()
  await page.getByRole('heading', { name: 'Approve a write to Jira' }).waitFor()
  await finishLoading(page)
  await expect(page.getByRole('button', { name: /^Approve and write to/ })).toBeEnabled()
  await expectGoodWalk(page, `${info.project.name}/approval`)
})

test('the user switcher works with the keyboard alone', async ({ page }) => {
  await openFrozen(page, '/')
  const trigger = page.getByRole('button', { name: /Switch user/ })
  await tabTo(page, trigger)
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

test('the speed control works with the keyboard alone', async ({ page }) => {
  await openFrozen(page, '/runs/run_01JB8')
  await advance(page, 2_000)
  const radio = (name: string) => page.getByRole('radio', { name })

  await tabTo(page, radio('1x'))
  await expect(radio('1x'), 'Tab enters the speed control on the checked speed').toBeChecked()

  await page.keyboard.press('ArrowRight')
  await expect(radio('2x'), 'ArrowRight moves to 2x').toBeFocused()
  await expect(radio('2x')).toBeChecked()
  await expect(tracker(page), 'the run plays at 2x').toHaveAttribute('data-speed', '2')

  await page.keyboard.press('ArrowRight')
  await expect(radio('Instant'), 'ArrowRight moves to Instant').toBeChecked()
  await expect(tracker(page)).toHaveAttribute('data-speed', 'instant')
  await expect(tracker(page), 'Instant lands on the newest event').toHaveAttribute('data-at-head', 'true')

  await page.keyboard.press('ArrowLeft')
  await expect(radio('2x'), 'ArrowLeft moves back to 2x').toBeChecked()
  await expect(tracker(page)).toHaveAttribute('data-speed', '2')
})

test('an Approver approves in place with the keyboard alone', async ({ page }) => {
  await openFrozen(page, '/')
  await switchUser(page, 'Bob')
  const approve = page.getByRole('region', { name: 'Approval' }).getByRole('button', { name: 'Approve', exact: true })
  await advanceUntil(page, approve)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())

  await tabTo(page, approve)
  await page.keyboard.press('Enter')
  await advanceUntil(page, page.locator('li[data-gate="open"]'))
  await expect(page.getByRole('region', { name: 'Approval' }), 'the approval panel closes once Bob decides').toHaveCount(0)
  await expect(headline(page), 'focus moves to the headline when the panel it was in closes').toBeFocused()
  const ring = await headline(page).evaluate((el) => {
    const style = getComputedStyle(el)
    return { style: style.outlineStyle, width: parseFloat(style.outlineWidth) }
  })
  expect(ring.style, 'the focused headline shows its ring').not.toBe('none')
  expect(ring.width, 'the ring is at least 2 px').toBeGreaterThanOrEqual(2)
  await advanceUntil(page, headline(page).getByText('MOCK-143 is in Jira', { exact: true }))
})
