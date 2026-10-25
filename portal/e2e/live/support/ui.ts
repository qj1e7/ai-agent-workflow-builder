import { expect, type Browser, type BrowserContext, type Page, type TestInfo } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { tracker } from '../../support/flows'
import type { Backend } from './stack'

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

/**
 * Starts a run of the release check from the Builder and resolves with the new run id once the run page is open.
 *
 * The Builder now plans with an AI model, and the live stack has none connected for these specs. The release check
 * is still a template, so the helper saves it through the API as Alice (the way the Portal did before), reloads the
 * Builder, and presses Run now on it under "Your use cases". Agent cards on the live stack are proven by the
 * platform's own end-to-end suite, which connects a mock model.
 */
export async function runExampleFromBuilder(page: Page, info: TestInfo, backend: Backend, label: string): Promise<string> {
  const proof = backend.proofOf('alice')
  const { templates } = await backend.get<{ templates: { key: string; params: { name: string; example: string }[] }[] }>('alice', '/api/v1/templates')
  const template = templates.find((each) => each.key === 'release_check')
  expect(template, 'the platform offers the release check').toBeDefined()
  const name = `Release check ${label}`
  const saved = await page.request.post('/api/v1/use-cases', {
    headers: proof,
    data: {
      template: 'release_check',
      name,
      instruction: 'Check langchain-ai/langgraph for new releases and open a ticket for the team.',
      params: Object.fromEntries((template?.params ?? []).map((param) => [param.name, param.example])),
    },
  })
  expect(saved.status(), 'the release check is saved').toBe(201)

  await openBuilder(page)
  await shot(page, info, `${label}-01-builder-empty`)
  const row = page.getByRole('listitem').filter({ has: page.getByRole('heading', { level: 3, name }) })
  await expect(row).toBeVisible()
  await shot(page, info, `${label}-02-builder-use-case`)
  await row.getByRole('button', { name: 'Run now' }).click()
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  return new URL(page.url()).pathname.split('/').pop() as string
}
