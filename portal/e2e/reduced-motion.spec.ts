import { type Page } from '@playwright/test'
import { openFrozen } from './support/clock'
import { waitingForApprover } from './support/flows'
import { movingAnimations, MOVING, type MovingAnimation } from './support/motion'
import { record } from './support/record'
import { expect, test } from './support/test'

const STEP_MS = 500
const LIMIT_MS = 40_000

async function sample(page: Page): Promise<MovingAnimation[]> {
  return page.evaluate(movingAnimations, MOVING)
}

async function playToPause(page: Page): Promise<{ moving: MovingAnimation[]; samples: number }> {
  const moving: MovingAnimation[] = []
  let samples = 0
  const pause = waitingForApprover(page)
  for (let spent = 0; spent < LIMIT_MS && !(await pause.isVisible()); spent += STEP_MS) {
    await page.clock.runFor(STEP_MS)
    await page.waitForTimeout(60)
    moving.push(...(await sample(page)))
    await page.waitForTimeout(120)
    moving.push(...(await sample(page)))
    samples += 2
  }
  await page.waitForTimeout(1_200)
  moving.push(...(await sample(page)))
  return { moving, samples }
}

async function opacityOf(page: Page, text: string | RegExp): Promise<number> {
  return page.getByText(text).first().evaluate((el) => {
    let opacity = 1
    for (let node: Element | null = el; node; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity)
    return opacity
  })
}

test('with reduced motion nothing travels, and the approval pause is still fully readable', async ({ page }, info) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await openFrozen(page, '/runs/run_01JB8')
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), 'the browser is asking for reduced motion').toBe(true)

  const { moving, samples } = await playToPause(page)
  expect(samples, 'sampled animations through the run until the pause').toBeGreaterThan(10)
  expect(moving, 'running animations that move something under reduced motion').toEqual([])

  await expect(waitingForApprover(page), 'the action card says the run is waiting').toBeVisible()
  await expect(page.getByText(/^Waiting \d+/).first(), 'the seat shows its waiting counter').toBeVisible()
  await expect(page.getByText('Waiting for an Approver', { exact: true }).first(), 'the ticket shows its waiting status').toBeVisible()
  for (const text of [/^Waiting \d+/, 'Waiting for an Approver']) {
    expect(await opacityOf(page, text), `${text} is fully opaque, not mid-fade`).toBeGreaterThan(0.99)
  }
  await record(page, info, 'reduced-motion-pause')
})

test('the same sampler sees things travel when motion is allowed', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await openFrozen(page, '/runs/run_01JB8')
  const { moving } = await playToPause(page)
  expect(moving.length, 'moving animations seen without reduced motion, which proves the sampler can see them').toBeGreaterThan(0)
})
