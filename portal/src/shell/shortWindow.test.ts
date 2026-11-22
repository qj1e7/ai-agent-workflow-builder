/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// Vitest blanks a CSS import, even with ?raw.
const css = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const shortWindowQueries = (text: string) => [...text.matchAll(/@media \(max-height: ([^)]+)\)/g)].map((match) => match[1])

describe('the chat on a short window', () => {
  it('lets the page scroll and docks the box at one and the same height', () => {
    const page = shortWindowQueries(css('./Shell.module.css'))
    const chat = shortWindowQueries(css('../screens/home/Planner.module.css'))
    expect(page).toHaveLength(1)
    expect(chat).toEqual(page)
  })
})
