import { describe, expect, it } from 'vitest'
import { formatDayAndTimeSeconds } from './useCaseTime'

describe('the time a use case row shows', () => {
  it('writes the day, the month, then the time down to the second', () => {
    expect(formatDayAndTimeSeconds('2026-10-21T05:51:07Z')).toMatch(/^\d{1,2} Oct, \d\d:\d\d:07$/)
  })

  it('tells apart two use cases saved in the same minute', () => {
    expect(formatDayAndTimeSeconds('2026-10-21T05:51:07Z')).not.toBe(formatDayAndTimeSeconds('2026-10-21T05:51:41Z'))
  })
})
