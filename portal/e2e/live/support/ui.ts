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

/**
 * What Needs you on Workflows counts: its rows, plus the rest its note says the platform has not listed yet. The heading carries
 * no number, as in the sketch, so this is the number the strip, the Planner's answer and an Approver's Home heading must match.
 */
export async function needsOnWorkflows(page: Page): Promise<number> {
  const section = page.getByRole('main').getByRole('region', { name: 'Needs you' })
  await expect(section.locator('li[data-home-item]').first()).toBeVisible()
  const rows = await section.locator('li[data-home-item]').count()
  const note = section.locator('p').filter({ hasText: /\d+ more/ })
  const more = (await note.count()) === 0 ? 0 : Number(/(\d+) more/.exec(await note.innerText())?.[1] ?? 0)
  return rows + more
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

/** The reasons Decline opens, before anything is declined (spec 10.4). */
export const declineReasons = (scope: Page | Locator): Locator => scope.getByRole('group', { name: /^Why are you declining\? Optional\./ })

/** Decline asks why first. This picks the reason when there is one, then declines. */
export async function decline(scope: Page | Locator, reason?: string): Promise<void> {
  await scope.getByRole('button', { name: 'Decline' }).click()
  const why = declineReasons(scope)
  if (reason !== undefined) await why.getByRole('button', { name: reason }).click()
  await why.getByRole('button', { name: 'Decline' }).click()
}
