import { describe, expect, it } from 'vitest'
import { parseSpeed } from './speed'

describe('the remembered speed', () => {
  it('reads 2x and Instant back, and anything else as 1x', () => {
    expect(parseSpeed('2')).toBe(2)
    expect(parseSpeed('instant')).toBe('instant')
    for (const stored of ['1', null, '', '3', 'fast', 'Instant']) expect(parseSpeed(stored)).toBe(1)
  })
})
