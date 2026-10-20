import type { Page } from '@playwright/test'
import { finishLoading } from './clock'

export async function switchUser(page: Page, name: string): Promise<void> {
  await page.getByRole('button', { name: /Switch user/ }).click()
  await page.getByRole('menuitemradio', { name: new RegExp(name) }).click()
  await finishLoading(page)
}

export async function goTo(page: Page, link: string): Promise<void> {
  await page.getByRole('link', { name: link, exact: true }).click()
  await page.locator('#main h1').waitFor()
  await finishLoading(page)
}
