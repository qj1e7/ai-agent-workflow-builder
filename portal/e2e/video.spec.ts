import { expect, test } from '@playwright/test'
import { mkdir, stat } from 'node:fs/promises'
import { outPath } from './support/record'
import { assertClean, watchPage } from './support/test'

const SUCCESS_LIMIT_MS = 75_000
const HOLD_ON_SUCCESS_MS = 4_000

test('records the overview from load through Bob approving to MOCK-142', async ({ browser }) => {
  test.setTimeout(SUCCESS_LIMIT_MS + 30_000)
  const size = { width: 1440, height: 900 }
  const context = await browser.newContext({
    viewport: size,
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
    recordVideo: { dir: outPath('results', 'video'), size },
  })
  const page = await context.newPage()
  const watch = watchPage(page)
  const video = page.video()
  expect(video, 'the page is recording').not.toBeNull()

  await page.goto('/')
  await page.locator('#main h1').waitFor()
  await expect(page.getByText('Waiting for an Approver', { exact: true }).first(), 'the run reaches the approval pause').toBeVisible({ timeout: SUCCESS_LIMIT_MS })
  await expect(page.getByText('Approved by Bob').first(), 'Bob approves').toBeVisible({ timeout: SUCCESS_LIMIT_MS })
  await expect(page.getByText('Written as MOCK-142').first(), 'the ticket is written').toBeVisible({ timeout: SUCCESS_LIMIT_MS })
  await expect(page.getByText('Finished', { exact: true }), 'the run finishes').toBeVisible({ timeout: SUCCESS_LIMIT_MS })
  await page.waitForTimeout(HOLD_ON_SUCCESS_MS)
  assertClean(watch)

  await mkdir(outPath('video'), { recursive: true })
  const target = outPath('video', 'overview-success.webm')
  await context.close()
  await video?.saveAs(target)
  expect((await stat(target)).size, 'the video file is not empty').toBeGreaterThan(50_000)
})
