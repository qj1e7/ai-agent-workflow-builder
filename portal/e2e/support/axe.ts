import type { Page } from '@playwright/test'
import axeCore, { type AxeResults } from 'axe-core'

const RESULT_TYPES: axeCore.resultGroups[] = ['violations', 'passes', 'incomplete', 'inapplicable']

/**
 * Runs axe inside the page under test and nowhere else. @axe-core/playwright opens a blank page in the same browser context to finish its run, and a clock
 * pump that runs while that page closes is rejected with "Target page, context or browser has been closed", because the clock belongs to the context.
 * The script is the one @axe-core/playwright injects, so the result has the same shape. It does not enter child frames, and the Portal has none.
 */
export async function analyzeInPage(page: Page): Promise<AxeResults> {
  const loaded = await page.evaluate(() => 'axe' in window)
  if (!loaded) await page.evaluate(axeCore.source)
  return page.evaluate((resultTypes) => (window as unknown as { axe: typeof axeCore }).axe.run(document, { resultTypes }), RESULT_TYPES)
}

/** The violations that fail a run: serious or critical, each with the nodes it names. Minor and moderate ones stay in the saved result. */
export function blockingViolations(axe: AxeResults): string[] {
  return axe.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`)
}
