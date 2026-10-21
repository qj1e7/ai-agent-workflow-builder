import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { blockingViolations } from '../support/axe'
import { headline } from '../support/flows'
import { outOfVisualOrder, walkTabs, withoutVisibleFocus } from '../support/keyboard'
import { expect, test } from './support/test'
import { CATCH_UP_MS, expectCaughtUp, openContext, OUT, shot } from './support/ui'

const STOP_KEYS = ['start', 'agent:read_releases', 'draft', 'gate', 'write:jira', 'done']
const STOP_NAMES = ['Started', 'Read GitHub releases', 'Draft ticket', 'Approval gate', 'Jira', 'Done']

/** Runs axe on the page as it is, saves the whole result under e2e/out/live/axe, and fails on a serious or critical violation. */
async function expectAccessible(page: Page, name: string): Promise<void> {
  const axe = await new AxeBuilder({ page }).analyze()
  await mkdir(path.join(OUT, 'axe'), { recursive: true })
  await writeFile(path.join(OUT, 'axe', `${name}.json`), JSON.stringify(axe, null, 2))
  expect(blockingViolations(axe), `${name}: serious or critical accessibility violations`).toEqual([])
}

/** The first screen's heading, its two actions, and the release check's line with nothing done. */
async function expectFirstScreen(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Start the first run')
  await expect(page.getByRole('button', { name: 'Run the example' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Describe your own task' })).toBeVisible()
  const stops = page.getByRole('region', { name: 'Steps in Release check' }).locator('li[data-stop]')
  await expect(stops, 'the line has the six stops of the release check').toHaveCount(STOP_KEYS.length)
  expect(await stops.evaluateAll((items) => items.map((item) => item.getAttribute('data-stop')))).toEqual(STOP_KEYS)
  await expect(stops, 'each stop shows its name').toContainText(STOP_NAMES)
  await expect(page.locator('li[data-stop][data-state="future"]'), 'nothing is done yet').toHaveCount(STOP_KEYS.length)
}

test('a fresh Portal opens on the line of the release check, and one click starts a real run that stops at the approval gate', async ({ page, browser, backend }, info) => {
  test.skip((await backend.runs()).length > 0, 'the stack already has runs, so there is no first screen to see')

  await page.goto('/')
  await expectFirstScreen(page)
  await shot(page, info, '00-first-screen-empty')
  await expectAccessible(page, '00-first-screen-empty')

  for (const [name, options] of [
    ['00-first-screen-empty-dark', { dark: true }],
    ['00-first-screen-empty-phone', { phone: true }],
    ['00-first-screen-empty-phone-dark', { phone: true, dark: true }],
  ] as const) {
    const context = await openContext(browser, options)
    const other = await context.newPage()
    await other.goto('/')
    await expectFirstScreen(other)
    await shot(other, info, name)
    await expectAccessible(other, name)
    await context.close()
  }

  const walk = await walkTabs(page)
  const labels = walk.stops.map((stop) => stop.label)
  const runStop = labels.indexOf('Run the example')
  const describeStop = labels.indexOf('Describe your own task')
  expect(runStop, `Tab reaches Run the example; stops: ${labels.join(', ')}`).toBeGreaterThanOrEqual(0)
  expect(describeStop, 'Tab reaches Describe your own task after Run the example').toBeGreaterThan(runStop)
  expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing or the same as at rest').toEqual([])
  expect(outOfVisualOrder(walk.stops), 'Tab moves that go against the visual order').toEqual([])

  const ticketsBefore = (await backend.tickets()).length
  await page.getByRole('button', { name: 'Run the example' }).click()
  await expect(page.getByRole('heading', { level: 1 }), 'the Tracker takes the overview with the new run').toHaveText('Release check', { timeout: 15_000 })

  const runs = await backend.runs()
  expect(runs, 'one click made exactly one run').toHaveLength(1)
  const run = runs[0]
  expect(run?.use_case_name).toBe('Release check')
  await backend.waitForState(run?.run_id ?? '', ['awaiting_approval'])
  expect((await backend.tickets()).length, 'the approval gate holds: nothing was written').toBe(ticketsBefore)
  await expect(headline(page), 'the Tracker reaches the approval gate').toHaveText('Waiting for an Approver', { timeout: CATCH_UP_MS })
  await expectCaughtUp(page)
  await shot(page, info, '00-first-run-awaiting-approval')
})
