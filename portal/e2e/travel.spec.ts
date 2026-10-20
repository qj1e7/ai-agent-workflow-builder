import { collisionSampler, type Collision } from './support/collisions'
import { transportSays } from './support/flows'
import { expect, test } from './support/test'

const RUN_LIMIT_MS = 75_000

test('nothing that travels or speaks covers a room label during the live run', async ({ page }) => {
  test.setTimeout(RUN_LIMIT_MS + 30_000)
  await page.goto('/')
  await page.locator('#main h1').waitFor()
  const labels = await page.locator('[data-room-label]').count()
  test.skip(labels === 0, 'No [data-room-label] element exists yet, so there is nothing to collide with. Add the data-room-label, data-travel, data-ticket and data-speech attributes to the room, then rerun.')

  const sampler = await collisionSampler(page)
  await expect(transportSays(page, 'Done'), 'the live run reaches its end').toBeVisible({ timeout: RUN_LIMIT_MS })
  const { collisions, samples } = await sampler.stop()
  expect(samples, 'sampled at roughly 10 Hz through the run').toBeGreaterThan(100)
  const worst: Collision[] = collisions.slice(0, 20)
  expect(worst, 'moving pieces, tickets or speech cards overlapping a room label by more than 1 px').toEqual([])
})
