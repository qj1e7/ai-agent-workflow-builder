import type { Browser, BrowserContext, Page, TestInfo } from '@playwright/test'
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
