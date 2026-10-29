import { describe, expect, it } from 'vitest'
import { greeting, today } from './today'

describe('greeting', () => {
  it.each([
    ['2026-10-28T16:00:00Z', 'Good morning'],
    ['2026-10-29T03:59:00Z', 'Good morning'],
    ['2026-10-29T04:00:00Z', 'Good afternoon'],
    ['2026-10-29T09:59:00Z', 'Good afternoon'],
    ['2026-10-29T10:00:00Z', 'Good evening'],
    ['2026-10-29T15:59:00Z', 'Good evening'],
  ])('at %s in Singapore says %s', (instant, words) => {
    expect(greeting(new Date(instant))).toBe(words)
  })
})

describe('today', () => {
  it('names the day by Singapore time, not by the time zone of the machine', () => {
    expect(today(new Date('2026-10-29T03:00:00Z'))).toBe('Thursday 29 October')
    expect(today(new Date('2026-10-28T17:00:00Z'))).toBe('Thursday 29 October')
  })
})
