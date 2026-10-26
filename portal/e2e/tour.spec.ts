import type { Locator, Page } from '@playwright/test'
import { advanceUntil, openFrozen } from './support/clock'
import { record } from './support/record'
import { isDesktop } from './support/states'
import { expect, test } from './support/test'

const card = (page: Page) => page.locator('[data-tour-card]')
const say = (page: Page, words: string | RegExp) => card(page).getByText(words)
const tourButton = (page: Page) => page.getByRole('button', { name: 'Tour', exact: true })
const userMenu = (page: Page) => page.getByRole('button', { name: /Switch user/ })
const themeButton = (page: Page) => page.getByRole('button', { name: /^Use (dark|light) theme$/ })
const pill = (page: Page) => page.getByRole('button', { name: /^Show the tour:/ })

/** The glow follows its stop frame by frame, and frames run only when the frozen clock moves. */
async function follow(page: Page): Promise<void> {
  await page.clock.runFor(100)
  await page.waitForTimeout(100)
}

async function expectGlowAround(page: Page, target: Locator, what: string): Promise<void> {
  await follow(page)
  const ring = await page.locator('[data-tour-glow]').boundingBox()
  const box = await target.boundingBox()
  expect(ring, `the glow shows on ${what}`).not.toBeNull()
  expect(box, `${what} is on screen`).not.toBeNull()
  if (!ring || !box) return
  const around = ring.x <= box.x && ring.y <= box.y && ring.x + ring.width >= box.x + box.width && ring.y + ring.height >= box.y + box.height
  expect(around, `the glow surrounds ${what}`).toBe(true)
}

test('a newcomer learns the Portal by doing each step, and the card ticks each one off', async ({ page }, info) => {
  await openFrozen(page, '/')
  await tourButton(page).click()
  await follow(page)
  await expect(card(page).getByRole('heading', { name: 'Find your way around' }), 'opening the tour moves focus to it').toBeFocused()
  await record(page, info, 'tour-start')

  await card(page).getByRole('button', { name: 'Next' }).click()
  await advanceUntil(page, say(page, 'Press your name at the top right.'))
  await expectGlowAround(page, userMenu(page), 'the user menu')
  await userMenu(page).click()
  // The demo starts as Alice, so "Act as Alice" is already met and ticks itself.
  await advanceUntil(page, say(page, /^Press the moon or the sun/))
  await page.keyboard.press('Escape')
  await themeButton(page).click()
  await advanceUntil(page, card(page).getByRole('heading', { name: 'Quest complete' }))
  await themeButton(page).click()
  await record(page, info, 'tour-quest-done')

  await card(page).getByRole('button', { name: 'Next quest' }).click()
  await advanceUntil(page, say(page, 'Press the gear at the top right.'))
  await page.getByRole('link', { name: 'Settings', exact: true }).first().click()
  await advanceUntil(page, say(page, /^If a green line names your model/))
  // Folded, the card is out of the way of the form, and it still notices the step being done.
  await card(page).getByRole('button', { name: 'Fold the tour' }).click()
  await page.getByLabel('Key', { exact: true }).fill('sk-example-key-not-real-x7')
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  await advanceUntil(page, page.getByText(/^Connected to AI Singapore gateway/))
  await page.getByRole('button', { name: 'Test and save' }).click()
  await advanceUntil(page, pill(page).filter({ hasText: 'Connect an AI model is done' }))
  await pill(page).click()

  await card(page).getByRole('button', { name: 'Next quest' }).click()
  await advanceUntil(page, say(page, 'Open the Builder from the menu.'))
  await page.getByRole('link', { name: 'Builder', exact: true }).first().click()
  await advanceUntil(page, say(page, 'Press Plan the example.'))
  const planExample = page.getByRole('button', { name: 'Plan the example' })
  await expectGlowAround(page, planExample, 'Plan the example')
  await planExample.click()
  await advanceUntil(page, say(page, /^Read the Room lead's plan/))
  if (isDesktop(info.project.name)) {
    const where = await card(page).boundingBox()
    expect(where?.x, 'the card moves left, off the plan it points at').toBeLessThan(100)
  }
  await record(page, info, 'tour-plan')

  await card(page).getByRole('button', { name: 'Next' }).click()
  await advanceUntil(page, say(page, /^Check the details under the agent/))
  await page.getByLabel('Jira project', { exact: true }).fill('MOCK')
  await card(page).getByRole('button', { name: 'Next' }).click()
  await advanceUntil(page, say(page, 'Press Save and run.'))
  await page.getByRole('button', { name: 'Save and run' }).click()
  await advanceUntil(page, card(page).getByRole('heading', { name: 'Quest complete' }))
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  await expect(card(page).getByText('Plan a task: done.')).toBeVisible()
})

test('the tour folds out of the way, keeps its place when closed, and Skip moves on without a tick', async ({ page }, info) => {
  await openFrozen(page, '/')
  await tourButton(page).click()
  await card(page).getByRole('button', { name: 'Next' }).click()
  await advanceUntil(page, say(page, 'Press your name at the top right.'))

  await page.keyboard.press('Escape')
  await expect(card(page), 'Escape inside the card folds it').toHaveCount(0)
  await expect(pill(page)).toContainText('Find your way around, step 2 of 4')
  await expect(page.locator('[data-tour-glow]'), 'a folded tour points at nothing').toHaveCount(0)
  await pill(page).click()
  await expect(say(page, 'Press your name at the top right.')).toBeVisible()

  await card(page).getByRole('button', { name: 'Close the tour' }).click()
  await expect(card(page)).toHaveCount(0)
  await expect(pill(page)).toHaveCount(0)
  await tourButton(page).click()
  await expect(say(page, 'Press your name at the top right.'), 'the flag opens the tour where it was left').toBeVisible()

  await card(page).getByRole('button', { name: 'Skip' }).click()
  await advanceUntil(page, say(page, /^Press the moon or the sun/))
  const steps = card(page).getByRole('list', { name: 'Steps in Find your way around' })
  if (isDesktop(info.project.name)) {
    await expect(steps.getByRole('listitem').nth(1), 'a skipped step is not ticked').toContainText('(skipped)')
  }
  // Back steps over "Act as Alice" too. The clock stands still, so it cannot tick itself again on the way.
  for (let press = 0; press < 3; press += 1) await card(page).getByRole('button', { name: 'Back' }).click()
  await expect(say(page, /^This tour runs on the real app/)).toBeVisible()
})
