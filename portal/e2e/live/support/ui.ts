import { expect, type Browser, type BrowserContext, type Page, type TestInfo } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { tracker } from '../../support/flows'

export const OUT = path.resolve('e2e/out/live')

/** The backend finishes its work in seconds; the Tracker tells the story at reading pace, so the page shows a state well after the backend reaches it. */
export const CATCH_UP_MS = 30_000

export const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 }

/** A second browser context at the given size and colour scheme, with the suite's locale and time zone. */
export function openContext(browser: Browser, { phone = false, dark = false } = {}): Promise<BrowserContext> {
  return browser.newContext({
    ...(phone ? { viewport: PHONE, isMobile: true, hasTouch: true } : { viewport: DESKTOP }),
    colorScheme: dark ? 'dark' : 'light',
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
}

/** The Tracker shows the newest event the backend has sent. */
export async function expectCaughtUp(page: Page): Promise<void> {
  await expect(tracker(page), 'the Tracker has caught up with the backend').toHaveAttribute('data-at-head', 'true', { timeout: CATCH_UP_MS })
}

/** Saves a shot of the viewport under e2e/out/live/shots, after a pause for CSS transitions. */
export async function shot(page: Page, info: TestInfo, name: string): Promise<void> {
  const dir = path.join(OUT, 'shots')
  await mkdir(dir, { recursive: true })
  await page.waitForTimeout(900)
  await page.screenshot({ path: path.join(dir, `${name}.png`), caret: 'hide' })
  info.annotations.push({ type: 'shot', description: name })
}

export async function openBuilder(page: Page): Promise<void> {
  await page.getByRole('link', { name: 'Builder', exact: true }).first().click()
  await expect(page).toHaveURL(/\/builder$/)
}

export async function switchUser(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: /Switch user/ }).click()
  await page.getByRole('menuitemradio', { name: new RegExp(name) }).click()
  await expect(page.getByRole('button', { name: /Switch user/ })).toContainText(name)
}

/** Plans the example task, saves it, and starts a run with Run now. Resolves with the new run id once the run page is open. */
export async function runExampleFromBuilder(page: Page, info: TestInfo, label: string): Promise<string> {
  await openBuilder(page)
  await shot(page, info, `${label}-01-builder-empty`)
  await page.getByRole('button', { name: 'Plan the example' }).click()
  await expect(page.getByRole('heading', { name: 'Matched your words' })).toBeVisible()
  await shot(page, info, `${label}-02-builder-planned`)
  await page.getByRole('button', { name: 'Save use case' }).click()
  await expect(page.getByText(/^Saved .+, version 1/)).toBeVisible()
  await shot(page, info, `${label}-03-builder-saved`)
  await page.getByRole('button', { name: 'Run now' }).first().click()
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  return new URL(page.url()).pathname.split('/').pop() as string
}
