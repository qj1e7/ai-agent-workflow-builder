import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

export async function expectAccessible(page: Page, outDir: string, name: string): Promise<void> {
  const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
  await mkdir(outDir, { recursive: true })
  await writeFile(path.join(outDir, `${name}.json`), JSON.stringify(result, null, 2))
  const found = result.violations.map((violation) => `${violation.id} (${violation.impact ?? 'unknown'}): ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`)
  expect(found, `${name}: WCAG 2.2 AA violations`).toEqual([])
}
