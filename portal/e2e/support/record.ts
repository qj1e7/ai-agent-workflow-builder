import { expect, type Page, type TestInfo } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { analyzeInPage, blockingViolations } from './axe'
import { pumpWhile } from './clock'
import { withoutKnown } from './known'
import { measureLayout, MIN_TARGET, MIN_TEXT } from './layout'
import type { StateName } from './states'

const MAX_FULL_HEIGHT = 6000
export const OUT = path.resolve('e2e/out')

export function outPath(...parts: string[]): string {
  return path.join(OUT, ...parts)
}

interface RecordOptions {
  /** Take the viewport only, for states that are about where the page is scrolled to. */
  viewportOnly?: boolean
}

/** Saves the shot, runs axe and the layout guards on the state the page is in. Failures are soft so one test reports every state. */
export async function record(page: Page, info: TestInfo, name: StateName, options: RecordOptions = {}): Promise<void> {
  const project = info.project.name

  const layout = await page.evaluate(measureLayout, { minTarget: MIN_TARGET, minText: MIN_TEXT })
  expect.soft(layout.overflow, `${project}/${name}: page scrolls sideways by this many px`).toBeLessThanOrEqual(0)
  expect.soft(layout.undersizedTargets, `${project}/${name}: interactive targets smaller than ${MIN_TARGET} by ${MIN_TARGET} px`).toEqual([])
  const smallText = withoutKnown(
    'small-text',
    `${project}/${name}`,
    layout.smallText.map((text) => `"${text.text}" at ${text.size}px in ${text.parent}`),
  )
  expect.soft(smallText, `${project}/${name}: visible text smaller than ${MIN_TEXT}px`).toEqual([])

  const axe = await pumpWhile(page, analyzeInPage(page))
  await mkdir(outPath('axe', project), { recursive: true })
  await writeFile(outPath('axe', project, `${name}.json`), JSON.stringify(axe, null, 2))
  expect.soft(blockingViolations(axe), `${project}/${name}: serious or critical accessibility violations`).toEqual([])

  await mkdir(outPath('shots', project), { recursive: true })
  const viewport = page.viewportSize()
  const height = await page.evaluate<number>('document.documentElement.scrollHeight')
  const scrolls = viewport !== null && height > viewport.height + 1
  if (options.viewportOnly || !scrolls) {
    await page.screenshot({ path: outPath('shots', project, `${name}.png`), caret: 'hide' })
    return
  }
  await page.screenshot({ path: outPath('shots', project, `${name}.viewport.png`), caret: 'hide' })
  // A tall viewport instead of fullPage, so fixed bars such as the phone tab bar sit at the real bottom.
  await page.setViewportSize({ width: viewport.width, height: Math.min(height, MAX_FULL_HEIGHT) })
  await page.waitForTimeout(300)
  await page.screenshot({ path: outPath('shots', project, `${name}.png`), caret: 'hide' })
  await page.setViewportSize(viewport)
  await page.waitForTimeout(300)
}
