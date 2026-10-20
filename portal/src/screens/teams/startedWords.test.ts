import { describe, expect, it } from 'vitest'
import { startedWords } from './startedWords'

describe('when a run started', () => {
  it('tells two runs apart that started in the same minute', () => {
    const first = startedWords('2026-10-20T19:00:14.297Z')
    const second = startedWords('2026-10-20T19:00:41.002Z')
    expect(first).toMatch(/^\d{1,2} \w{3}, \d\d:\d\d:14$/)
    expect(second).toMatch(/:41$/)
    expect(first).not.toBe(second)
  })
})
