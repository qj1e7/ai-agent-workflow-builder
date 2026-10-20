import { describe, expect, it } from 'vitest'
import { formatClock, formatDuration, formatRelative, shortDigest } from './format'
import { spineStateWords } from './spineState'

describe('formatDuration', () => {
  it('writes waits the way the transport labels them', () => {
    expect(formatDuration(42_000)).toBe('42 s')
    expect(formatDuration(373_000)).toBe('6 min 13 s')
    expect(formatDuration(3_900_000)).toBe('1 h 5 min')
    expect(formatClock(12_400)).toBe('0:12')
    expect(formatClock(386_000)).toBe('6:26')
  })
})

describe('formatRelative', () => {
  it('rounds to the unit a person would say', () => {
    const now = Date.parse('2026-11-27T12:00:00Z')
    expect(formatRelative('2026-11-27T11:59:50Z', now)).toBe('Just now')
    expect(formatRelative('2026-11-27T11:48:00Z', now)).toBe('12 min ago')
    expect(formatRelative('2026-11-27T09:00:00Z', now)).toBe('3 hours ago')
    expect(formatRelative('2026-11-26T12:00:00Z', now)).toBe('Yesterday')
  })
})

describe('shortDigest', () => {
  it('keeps the algorithm and the first and last characters', () => {
    expect(shortDigest('sha256:0be2129632d1283e015efcae22757aa3e182793e0153503bdd30dc0327a42576')).toBe('sha256:0be2…2576')
  })
})

describe('spineStateWords', () => {
  it('says each state in words, with the Approver and the wait', () => {
    expect(spineStateWords({ kind: 'waiting', waited: '6 min' })).toBe('Waiting for an Approver, 6 min')
    expect(spineStateWords({ kind: 'approved', by: 'Bob' })).toBe('Approved by Bob')
    expect(spineStateWords({ kind: 'failed' })).toBe('Stopped here')
  })
})
