/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(import.meta.dirname, '..')

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sources(path)
    return /\.(tsx|css)$/.test(name) ? [path] : []
  })
}

describe('the one pill', () => {
  it('is the only place a pill is styled, so no card can fall back to plain text by importing a deleted class', () => {
    const own = sources(SRC)
      .filter((path) => !path.endsWith('Pill.module.css') && !path.endsWith('Pill.tsx') && !path.includes('.test.'))
      .filter((path) => /\[['"]pill['"]\]|styles\.pill\b|^\.pill\b/m.test(readFileSync(path, 'utf8')))
    expect(own.map((path) => path.slice(SRC.length))).toEqual([])
  })

  it('lets a long pill shrink and wrap, with its icon on the first line, so it never overlaps its neighbour or widens the page', () => {
    const css = readFileSync(join(SRC, 'ui/Pill.module.css'), 'utf8')
    expect(css).toMatch(/min-width:\s*0/)
    expect(css).toMatch(/white-space:\s*normal/)
    expect(css).not.toMatch(/flex:\s*none;\s*\n\s*align-items/)
  })
})
