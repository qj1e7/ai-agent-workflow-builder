import { access } from 'node:fs/promises'
import { outPath } from './support/record'
import { PROJECTS, STATES, VIDEO } from './support/states'
import { expect, test } from '@playwright/test'

async function exists(...parts: string[]): Promise<boolean> {
  try {
    await access(outPath(...parts))
    return true
  } catch {
    return false
  }
}

test('every screenshot, axe report and the video exists after the other specs ran', async () => {
  const missing: string[] = []
  for (const project of PROJECTS) {
    for (const state of STATES) {
      if (!(await exists('shots', project, `${state}.png`))) missing.push(`shots/${project}/${state}.png`)
      if (!(await exists('axe', project, `${state}.json`))) missing.push(`axe/${project}/${state}.json`)
    }
  }
  if (!(await exists('video', VIDEO))) missing.push(`video/${VIDEO}`)
  expect(missing, 'evidence files that were not written').toEqual([])
})
