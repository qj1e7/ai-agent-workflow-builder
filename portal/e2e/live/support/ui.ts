import { expect, type Browser, type BrowserContext, type Locator, type Page, type TestInfo } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

export const OUT = path.resolve('e2e/out/live')

export const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 }

export function openContext(browser: Browser, { phone = false } = {}): Promise<BrowserContext> {
  return browser.newContext({
    ...(phone ? { viewport: PHONE, isMobile: true, hasTouch: true } : { viewport: DESKTOP }),
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
}

export async function devContext(browser: Browser, user: string, { phone = false, reducedMotion = false } = {}): Promise<BrowserContext> {
  const context = await browser.newContext({
    ...(phone ? { viewport: PHONE, isMobile: true, hasTouch: true } : { viewport: DESKTOP }),
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
    ...(reducedMotion ? { reducedMotion: 'reduce' as const } : {}),
  })
  await context.addInitScript((id) => {
    try {
      window.localStorage.setItem('portal.dev-user', id)
    } catch {
      // A page without storage signs in as the default person.
    }
  }, user)
  return context
}

/** Saves a shot of the viewport under e2e/out/live/shots, after a pause for CSS transitions. */
export async function shot(page: Page, info: TestInfo, name: string): Promise<void> {
  const dir = path.join(OUT, 'shots')
  await mkdir(dir, { recursive: true })
  await page.waitForTimeout(900)
  await page.screenshot({ path: path.join(dir, `${name}.png`), caret: 'hide' })
  info.annotations.push({ type: 'shot', description: name })
}

/** Presses Show more under a list until it goes, so every row the list counts is drawn, and says how many rows there are then. */
export async function showEvery(list: Locator, rows: Locator): Promise<number> {
  const more = list.getByRole('button', { name: 'Show more', exact: true })
  while ((await more.count()) > 0) {
    const before = await rows.count()
    await more.click()
    await expect.poll(async () => (await more.count()) === 0 || (await rows.count()) > before, { message: 'Show more drew the next rows' }).toBe(true)
  }
  return rows.count()
}

/**
 * The rows of Needs you on Workflows, every one, after Show more has read each page. The heading carries no number, as in the
 * sketch, so this is the number the strip, the Planner's answer and an Approver's Home heading must match.
 */
export async function needsOnWorkflows(page: Page): Promise<number> {
  const section = page.getByRole('main').getByRole('region', { name: 'Needs you' })
  await expect(section.locator('li[data-home-item]').first()).toBeVisible()
  return showEvery(section, section.locator('li[data-home-item]'))
}

/** A page someone who isn't an Operator reads: one note naming the Operators, and no control there that is dead. */
export async function expectReadOnly(page: Page, what: string): Promise<void> {
  const main = page.getByRole('main')
  const note = main.getByText(/^Only Operators change /)
  await expect(note).toHaveCount(1)
  await expect(note).toHaveText(new RegExp(`^Only Operators change ${what}\\. Ask .*Alice.*Carol.*\\.$`))
  await expect(note).not.toContainText('Bob')
  await expect(main.locator(':is(button, input, select, textarea):disabled, [aria-disabled="true"]')).toHaveCount(0)
}

/** "What happened (3 steps)", the run's history, folded once the run needs the person or is over. */
const HISTORY = /^What happened \(\d+ steps?\)$/

/** Opens What happened when it is folded, so its steps, its run line and its agent messages can be read. Shut or open, it leaves it open. */
export async function showHistory(scope: Page | Locator): Promise<void> {
  const summary = scope.locator('summary', { hasText: HISTORY })
  await summary.waitFor()
  const details = scope.locator('details', { has: summary })
  if (!(await details.evaluate((element) => (element as HTMLDetailsElement).open))) await summary.click()
  await expect(details).toHaveJSProperty('open', true)
}

/** The reasons Decline opens, before anything is declined (spec 10.4). */
export const declineReasons = (scope: Page | Locator): Locator => scope.getByRole('group', { name: /^Why\? Optional\./ })

/** Decline asks why first. This picks the reason when there is one, then declines. */
export async function decline(scope: Page | Locator, reason?: string): Promise<void> {
  await scope.getByRole('button', { name: 'Decline' }).click()
  const why = declineReasons(scope)
  if (reason !== undefined) await why.getByRole('button', { name: reason }).click()
  await why.getByRole('button', { name: 'Decline' }).click()
}

/**
 * An answer about one run shows it beside the chat by itself on a wide screen, and offers Open on a narrow one (the sketch's
 * auto-open). Waits for the first, presses the second.
 */
export async function showRun(page: Page, opener: Locator): Promise<void> {
  if ((page.viewportSize()?.width ?? 0) > 900) await expect(page.locator('#side-panel'), 'on a wide screen the run opens beside the chat by itself').toBeVisible({ timeout: 20_000 })
  else await opener.click()
}
