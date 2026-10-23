import { test as base, expect, type Page } from '@playwright/test'

export interface Watch {
  cspViolations: string[]
  pageErrors: string[]
}

export function watchPage(page: Page): Watch {
  const watch: Watch = { cspViolations: [], pageErrors: [] }
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) watch.cspViolations.push(message.text())
  })
  page.on('pageerror', (error) => watch.pageErrors.push(String(error)))
  return watch
}

export function assertClean(watch: Watch): void {
  expect(watch.cspViolations, 'no Content Security Policy violations in the console').toEqual([])
  expect(watch.pageErrors, 'no uncaught page errors').toEqual([])
}

export const test = base.extend<{ watch: Watch }>({
  watch: [
    async ({ page }, use) => {
      const watch = watchPage(page)
      await use(watch)
      assertClean(watch)
    },
    { auto: true },
  ],
})

export { expect }
