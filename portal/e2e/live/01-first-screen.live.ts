import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { blockingViolations } from '../support/axe'
import { outOfVisualOrder, walkTabs, withoutVisibleFocus } from '../support/keyboard'
import { expect, test } from './support/test'
import { OUT, shot } from './support/ui'

const PHONE = { width: 390, height: 844 }
const IN_THE_ROOM = ['Room lead', 'Release checker', 'Alice', 'Approver', 'GitHub', 'Jira', 'Teams']
const caughtUp = (page: Page) => page.getByRole('status').filter({ hasText: 'Live' })

/** Runs axe on the page as it is, saves the whole result under e2e/out/live/axe, and fails on a serious or critical violation. */
async function expectAccessible(page: Page, name: string): Promise<void> {
  const axe = await new AxeBuilder({ page }).analyze()
  await mkdir(path.join(OUT, 'axe'), { recursive: true })
  await writeFile(path.join(OUT, 'axe', `${name}.json`), JSON.stringify(axe, null, 2))
  expect(blockingViolations(axe), `${name}: serious or critical accessibility violations`).toEqual([])
}

test('a fresh Portal opens on a set room, and one click starts a real run that stops at the approval gate', async ({ page, browser, backend }, info) => {
  test.skip((await backend.runs()).length > 0, 'the stack already has runs, so there is no first screen to see')

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Start the first run')
  const runTheExample = page.getByRole('button', { name: 'Run the example' })
  await expect(runTheExample).toBeVisible()
  await expect(page.getByRole('link', { name: 'Describe your own task' })).toBeVisible()
  // The drawn room is aria-hidden, so its words are found by text inside the stage, not by role.
  const stage = page.locator('[data-stage]')
  for (const name of IN_THE_ROOM) {
    await expect(stage.getByText(name, { exact: true }).first(), `the set room shows ${name}`).toBeVisible()
  }
  await shot(page, info, '00-first-screen-empty')
  await expectAccessible(page, '00-first-screen-empty')

  const phone = await browser.newContext({ viewport: PHONE, isMobile: true, hasTouch: true, locale: 'en-SG', timezoneId: 'Asia/Singapore' })
  const phonePage = await phone.newPage()
  await phonePage.goto('/')
  await expect(phonePage.getByRole('button', { name: 'Run the example' })).toBeVisible()
  await shot(phonePage, info, '00-first-screen-empty-phone')
  await expectAccessible(phonePage, '00-first-screen-empty-phone')
  await phone.close()

  const walk = await walkTabs(page)
  const labels = walk.stops.map((stop) => stop.label)
  const runStop = labels.indexOf('Run the example')
  const describeStop = labels.indexOf('Describe your own task')
  expect(runStop, `Tab reaches Run the example; stops: ${labels.join(', ')}`).toBeGreaterThanOrEqual(0)
  expect(describeStop, 'Tab reaches Describe your own task after Run the example').toBeGreaterThan(runStop)
  expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing or the same as at rest').toEqual([])
  expect(outOfVisualOrder(walk.stops), 'Tab moves that go against the visual order').toEqual([])

  const ticketsBefore = (await backend.tickets()).length
  await runTheExample.click()
  await expect(page.getByRole('heading', { level: 1 }), 'the hero takes the stage with the new run').toHaveText('Release check', { timeout: 15_000 })

  const runs = await backend.runs()
  expect(runs, 'one click made exactly one run').toHaveLength(1)
  const run = runs[0]
  expect(run?.use_case_name).toBe('Release check')
  await backend.waitForState(run?.run_id ?? '', ['awaiting_approval'])
  await expect(page.getByRole('heading', { name: /waiting for an Approver/ })).toBeVisible({ timeout: 30_000 })
  expect((await backend.tickets()).length, 'the approval gate holds: nothing was written').toBe(ticketsBefore)
  await expect(caughtUp(page), 'the room has caught up with the backend').toBeVisible({ timeout: 30_000 })
  await shot(page, info, '00-first-run-awaiting-approval')
})
