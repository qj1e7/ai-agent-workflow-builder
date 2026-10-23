import type { Locator, Page } from '@playwright/test'
import { setTimeout as delay } from 'node:timers/promises'

export const START = Date.parse('2026-11-27T10:14:00+08:00')
const LOADED_AT = START + 3_000
// CSS transitions and Web Animations run on the real clock, so every clock jump needs a real pause before a shot.
export const SETTLE_MS = 1_200

export async function openFrozen(page: Page, path: string): Promise<void> {
  await page.clock.install({ time: START })
  await page.goto(path)
  await page.locator('#main h1').waitFor()
  await page.clock.pauseAt(LOADED_AT)
  await settle(page)
}

export async function settle(page: Page, ms = SETTLE_MS): Promise<void> {
  await page.waitForTimeout(ms)
}

export async function advance(page: Page, ms: number, settleMs = SETTLE_MS): Promise<void> {
  await page.clock.runFor(ms)
  await settle(page, settleMs)
}

/** Lets a freshly opened page finish its loading skeletons. */
export async function finishLoading(page: Page, stepMs = 250, limitMs = 20_000): Promise<void> {
  const skeleton = page.getByText(/^Loading/)
  let spent = 0
  do {
    await page.clock.runFor(stepMs)
    spent += stepMs
    await page.waitForTimeout(60)
  } while ((await skeleton.count()) > 0 && spent < limitMs)
  await settle(page)
}

/** Moves the frozen clock in small steps until the state shows on screen, so a shot never depends on how long the page took to load. */
export async function advanceUntil(page: Page, ready: Locator, { stepMs = 250, limitMs = 90_000 } = {}): Promise<void> {
  let spent = 0
  while (!(await ready.first().isVisible())) {
    if (spent >= limitMs) throw new Error(`Gave up after ${limitMs} ms of page time waiting for the state to show (see the call site in the stack)`)
    await page.clock.runFor(stepMs)
    spent += stepMs
    await page.waitForTimeout(40)
  }
  await settle(page)
}

const PUMP_EVERY_MS = 10

// axe schedules its own work with setTimeout, so on a frozen page it needs the clock to creep forward while it runs.
// The clock belongs to the whole browser context, so the work must not open or close another page in it.
export async function pumpWhile<T>(page: Page, work: Promise<T>): Promise<T> {
  let settled = false
  const done = work.then(
    () => {
      settled = true
    },
    () => {
      settled = true
    },
  )
  while (!settled) {
    await page.clock.runFor(1)
    await Promise.race([done, delay(PUMP_EVERY_MS)])
  }
  return work
}
