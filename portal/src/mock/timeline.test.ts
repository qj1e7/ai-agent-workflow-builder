import { describe, expect, it } from 'vitest'
import { beatMsOf, isStory } from '../run'
import { fixtures } from './fixtures'
import { replay, SHORT_GAP_CAP_MS, SQUEEZE, Timeline, WAIT_HEAD_MS } from './timeline'

const START = 1_000_000

const SCHEDULE: readonly (readonly [seq: number, wall: number])[] = [
  [1, 0],
  [2, 180],
  [3, 1180],
  [4, 1470],
  [5, 2470],
  [6, 5345],
  [7, 6345],
  [8, 7945],
  [9, 8845],
  [10, 10445],
  [11, 13770],
  [12, 16345],
  [13, 16403],
  [14, 17403],
  [15, 17745],
  [16, 17761],
  [17, 19345],
  [18, 32566],
  [19, 32729],
  [20, 33729],
  [21, 34366],
  [22, 34393],
  [23, 36566],
]

const entries = replay(fixtures.successEvents, { wall: START, recorded: START })
const entry = (seq: number) => {
  const found = entries.find((candidate) => candidate.event.seq === seq)
  if (!found) throw new Error(`no seq ${seq}`)
  return found
}
const recordedGap = (seq: number) => Date.parse(fixtures.successEvents[seq - 1]?.ts ?? '') - Date.parse(fixtures.successEvents[seq - 2]?.ts ?? '')

describe('the demo pace', () => {
  it('lands every event of the success recording at the scheduled time', () => {
    expect(entries.map((candidate) => [candidate.event.seq, candidate.at - START])).toEqual(SCHEDULE)
  })

  it('never lands a story event before the previous story beat has played, and caps a short gap at a second', () => {
    let lastStory: (typeof entries)[number] | null = null
    for (const candidate of entries) {
      if (!isStory(candidate.event)) continue
      if (lastStory) expect(candidate.at, `seq ${candidate.event.seq}`).toBeGreaterThanOrEqual(lastStory.at + beatMsOf(lastStory.event))
      lastStory = candidate
    }
    expect(entry(5).at - entry(4).at, 'the ask waits for the join beat').toBe(beatMsOf(entry(4).event))
    expect(entry(7).at - entry(6).at, 'the fetch return is capped').toBe(SHORT_GAP_CAP_MS)
    expect(recordedGap(7)).toBeGreaterThan(SHORT_GAP_CAP_MS)
    expect(entry(12).at - entry(11).at, 'the proposal waits for the agreement to be read').toBe(beatMsOf(entry(11).event))
  })

  it('replays the 372.8 s wait for the decision in 13.2 s, with the recorded clock advancing the real gap', () => {
    expect(recordedGap(18)).toBe(372_835)
    expect(entry(18).at - entry(17).at).toBe(13_221)
    expect(entry(18).squeezed).toBe(true)
    expect(entry(18).ts - entry(17).ts).toBe(372_835)
    expect(entries.filter((candidate) => candidate.squeezed).map((candidate) => candidate.event.seq)).toEqual([18])
  })

  it('stamps each event with a recorded time that moves with the wall outside the wait, so the run clock stays 1:1', () => {
    const skipped = 372_835 - 13_221
    for (const candidate of entries) {
      const ahead = candidate.event.seq >= 18 ? skipped : 0
      expect(candidate.ts - START, `seq ${candidate.event.seq}`).toBe(candidate.at - START + ahead)
      expect(Date.parse(candidate.event.ts)).toBe(candidate.ts)
    }
  })
})

describe('the replay clock', () => {
  const timeline = new Timeline(entries)
  const announced = entry(17)
  const decided = entry(18)

  it('runs at real speed through the short gaps, with a rate of 1', () => {
    expect(timeline.recordedAt(START + 3000)).toBe(START + 3000)
    expect(timeline.rateAt(START + 3000)).toBe(1)
    expect(timeline.recordedAt(START - 500)).toBe(START - 500)
    expect(timeline.rateAt(START - 500)).toBe(1)
  })

  it('runs the head of the wait at real speed, then forty times faster, and lands on the recorded time of the decision', () => {
    expect(timeline.recordedAt(announced.at + WAIT_HEAD_MS)).toBe(announced.ts + WAIT_HEAD_MS)
    expect(timeline.rateAt(announced.at + WAIT_HEAD_MS)).toBe(1)
    expect(timeline.recordedAt(announced.at + WAIT_HEAD_MS + 1000)).toBe(announced.ts + WAIT_HEAD_MS + 1000 * SQUEEZE)
    expect(timeline.rateAt(announced.at + WAIT_HEAD_MS + 1)).toBe(SQUEEZE)
    expect(timeline.rateAt(decided.at - 1)).toBe(SQUEEZE)
    expect(timeline.recordedAt(decided.at - 1)).toBeLessThanOrEqual(decided.ts)
    expect(timeline.recordedAt(decided.at)).toBe(decided.ts)
    expect(timeline.rateAt(decided.at)).toBe(1)
  })

  it('keeps counting in real time after the last event', () => {
    const last = entries.at(-1)
    if (!last) throw new Error('no entries')
    expect(timeline.recordedAt(timeline.lastAt + 5000)).toBe(last.ts + 5000)
    expect(timeline.rateAt(timeline.lastAt + 5000)).toBe(1)
  })
})
