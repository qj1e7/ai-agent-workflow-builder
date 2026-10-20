import { describe, expect, it } from 'vitest'
import { runTime, wallTime } from './brand'
import { LONG_GAP_MS } from './director'
import { recording, slice } from './recordings'
import { layoutScrubber, SCRUB } from './scrubber'
import { createTape } from './tape'
import { TEST_REGISTRY } from './testing'

function marksOf(events: ReturnType<typeof recording>) {
  const tape = createTape(TEST_REGISTRY)
  tape.append(events, 'backlog', wallTime(0))
  return tape.marks()
}

const SUCCESS = recording('success')
const at = (seq: number) => SUCCESS[seq - 1]?.at ?? 0

describe('layoutScrubber', () => {
  it('draws the six minute wait as one fixed segment labelled with its real length', () => {
    const track = layoutScrubber({ marks: marksOf(SUCCESS), width: 600, edge: null })
    const G = Math.min(SCRUB.waitMaxPx, Math.max(SCRUB.waitMinPx, Math.round(600 * SCRUB.waitShare)))
    expect(track.waits).toEqual([
      { x: track.xOf(17), w: G, fill: G, lasted: at(18) - at(15), tone: 'person', live: false },
    ])
    expect(track.xOf(18) - track.xOf(17)).toBe(G)
  })

  it('keeps the axis honest: x grows with seq, from 0 to the width', () => {
    const track = layoutScrubber({ marks: marksOf(SUCCESS), width: 600, edge: null })
    expect(track.xOf(0)).toBe(0)
    expect(track.xOf(23)).toBe(600)
    for (let seq = 1; seq <= 23; seq += 1) expect(track.xOf(seq)).toBeGreaterThanOrEqual(track.xOf(seq - 1))
    expect(track.ticks.map((tick) => tick.seq)).toEqual(SUCCESS.filter((e) => !['leg_dispatched', 'step_started', 'step_finished'].includes(e.kind)).map((e) => e.seq))
  })

  it('reserves the live wait at the right edge from the first second and fills it over thirty seconds', () => {
    const marks = marksOf(slice('success', 1, 17))
    const since = runTime(at(15))
    const G = Math.min(SCRUB.waitMaxPx, Math.max(SCRUB.waitMinPx, Math.round(600 * SCRUB.waitShare)))
    const early = layoutScrubber({ marks, width: 600, edge: { now: runTime(at(17) + 12_400), waitingSince: since } })
    expect(early.waits).toEqual([
      { x: 600 - G, w: G, fill: Math.round((G * 12_400) / LONG_GAP_MS), lasted: at(17) + 12_400 - at(15), tone: 'person', live: true },
    ])
    const late = layoutScrubber({ marks, width: 600, edge: { now: runTime(at(17) + 6 * 60_000), waitingSince: since } })
    expect(late.waits[0]).toMatchObject({ w: G, fill: G, lasted: at(17) + 6 * 60_000 - at(15), live: true })
    expect(late.xOf(17)).toBe(early.xOf(17))
    expect(early.xOf(17)).toBe(600 - G)
  })

  it('inverts itself on every tick', () => {
    const track = layoutScrubber({ marks: marksOf(SUCCESS), width: 600, edge: null })
    for (const tick of track.ticks) expect(track.cursorAt(tick.x)).toBe(tick.seq)
    expect(track.cursorAt(-5)).toBe(1)
    expect(track.cursorAt(10_000)).toBe(23)
  })

  it('keeps bursts apart with a minimum tick spacing', () => {
    const track = layoutScrubber({ marks: marksOf(SUCCESS), width: 600, edge: null })
    for (let i = 1; i < track.ticks.length; i += 1) {
      const a = track.ticks[i - 1]!
      const b = track.ticks[i]!
      expect(b.x - a.x).toBeGreaterThan(0)
    }
  })

  it('handles an empty tape', () => {
    const track = layoutScrubber({ marks: [], width: 600, edge: null })
    expect(track.ticks).toEqual([])
    expect(track.xOf(0)).toBe(0)
    expect(track.cursorAt(300)).toBe(0)
  })
})
