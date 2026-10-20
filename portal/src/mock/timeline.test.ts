import { describe, expect, it } from 'vitest'
import { fixtures } from './fixtures'
import { replay, squeezeGap, Timeline } from './timeline'

describe('squeezeGap', () => {
  it('keeps short gaps at real speed and shrinks a long one by sixty beyond four seconds', () => {
    expect(squeezeGap(2500)).toBe(2500)
    expect(squeezeGap(4000)).toBe(4000)
    expect(squeezeGap(64_000)).toBe(5000)
  })
})

describe('the replay clock', () => {
  const start = 1_000_000
  const timeline = new Timeline(replay(fixtures.successEvents, { wall: start, recorded: start }))
  const requested = timeline.emitted(Infinity).find((event) => event.seq === 17)
  const requestedTs = Date.parse(requested?.ts ?? '')

  it('runs at real speed through the short gaps', () => {
    expect(timeline.recordedAt(start + 3000)).toBe(start + 3000)
  })

  it('runs sixty times faster through the squeezed wait and lands on the recorded time of the decision', () => {
    const at17 = start + 10_612
    expect(timeline.recordedAt(at17 + 4000)).toBe(requestedTs + 4000)
    expect(timeline.recordedAt(at17 + 5000)).toBe(requestedTs + 4000 + 60_000)
    const decision = timeline.emitted(Infinity).find((event) => event.seq === 18)
    const decidedAt = at17 + squeezeGap(Date.parse(decision?.ts ?? '') - requestedTs)
    expect(timeline.recordedAt(decidedAt)).toBeCloseTo(Date.parse(decision?.ts ?? ''), -1)
  })

  it('keeps counting in real time after the last event', () => {
    const last = timeline.emitted(Infinity).at(-1)
    expect(timeline.recordedAt(timeline.lastAt + 5000)).toBe(Date.parse(last?.ts ?? '') + 5000)
  })
})
