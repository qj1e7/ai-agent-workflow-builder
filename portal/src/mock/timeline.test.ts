import { describe, expect, it } from 'vitest'
import { fixtures } from './fixtures'
import { replay, squeezeGap, Timeline } from './timeline'

describe('squeezeGap', () => {
  it('keeps short gaps at real speed and shrinks a long one by forty beyond four seconds', () => {
    expect(squeezeGap(2500)).toBe(2500)
    expect(squeezeGap(4000)).toBe(4000)
    expect(squeezeGap(44_000)).toBe(5000)
  })

  it("replays the demo's 372.8 s wait for the decision in 13.2 s", () => {
    expect(squeezeGap(372_800)).toBe(13_220)
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

  it('runs forty times faster through the squeezed wait and lands on the recorded time of the decision', () => {
    const at17 = start + 10_612
    expect(timeline.recordedAt(at17 + 4000)).toBe(requestedTs + 4000)
    expect(timeline.recordedAt(at17 + 5000)).toBe(requestedTs + 4000 + 40_000)
    const decision = timeline.emitted(Infinity).find((event) => event.seq === 18)
    const decidedAt = at17 + squeezeGap(Date.parse(decision?.ts ?? '') - requestedTs)
    expect(timeline.recordedAt(decidedAt)).toBeCloseTo(Date.parse(decision?.ts ?? ''), -1)
  })

  it('keeps counting in real time after the last event', () => {
    const last = timeline.emitted(Infinity).at(-1)
    expect(timeline.recordedAt(timeline.lastAt + 5000)).toBe(Date.parse(last?.ts ?? '') + 5000)
  })
})
