/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('the Workflows table', () => {
  it('gives the state column room for its longest pill, "On · waiting for approval", so no pill wraps', () => {
    const css = readFileSync(join(import.meta.dirname, 'Workflows.module.css'), 'utf8')
    const first = /--cols:\s*([\d.]+)rem\s/.exec(css)
    expect(first, 'the first column is a width in rem').not.toBeNull()
    expect(Number(first?.[1])).toBeGreaterThanOrEqual(14.5)
  })
})
