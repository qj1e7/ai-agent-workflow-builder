import { describe, expect, it } from 'vitest'
import { wallTime } from './brand'
import { recording, slice } from './recordings'
import { EMPTY_ROOM } from './room'
import { createTape } from './tape'
import { TEST_REGISTRY } from './testing'

describe('createTape', () => {
  it('stores one frame per event and answers frame(0) with the empty room', () => {
    const tape = createTape(TEST_REGISTRY)
    expect(tape.append(recording('success'), 'backlog', wallTime(0))).toBe(23)
    expect(tape.length).toBe(23)
    expect(tape.frame(0)).toBe(EMPTY_ROOM)
    expect(tape.frame(17).phase.name).toBe('awaiting_approval')
    expect(tape.frame(23).phase.name).toBe('succeeded')
    expect(tape.event(5).kind).toBe('agent_message')
    expect(tape.move(12)).toMatchObject({ type: 'carry', token: 'ticket' })
    expect(tape.move(13)).toBeNull()
  })

  it('ignores a duplicate, an old or a skipped seq, so a restarted feed cannot corrupt the log', () => {
    const tape = createTape(TEST_REGISTRY)
    tape.append(slice('success', 1, 5), 'backlog', wallTime(0))
    expect(tape.append(slice('success', 3, 5), 'live', wallTime(10))).toBe(5)
    expect(tape.append(slice('success', 8, 9), 'live', wallTime(10))).toBe(5)
    expect(tape.append(slice('success', 4, 7), 'live', wallTime(20))).toBe(7)
    expect(tape.arrival(5)).toEqual({ at: 0, origin: 'backlog' })
    expect(tape.arrival(7)).toEqual({ at: 20, origin: 'live' })
  })

  it('marks story events on the timeline and remembers since when a person was needed', () => {
    const tape = createTape(TEST_REGISTRY)
    tape.append(recording('success'), 'backlog', wallTime(0))
    const marks = tape.marks()
    expect(marks).toHaveLength(23)
    expect(marks[1]).toMatchObject({ seq: 2, tier: 'technical', waitingSince: null })
    expect(marks[14]).toMatchObject({ seq: 15, tier: 'story', waitingSince: Date.parse('2026-11-03T02:14:08.244Z') })
    expect(marks[17]).toMatchObject({ seq: 18, tier: 'story', waitingSince: null })
  })

  it('writes a Minutes entry per event with its tier, raw kind and attempt', () => {
    const tape = createTape(TEST_REGISTRY)
    tape.append(recording('failure'), 'backlog', wallTime(0))
    const minutes = tape.minutes()
    expect(minutes[0]).toMatchObject({ seq: 1, kind: 'run_created', tier: 'story', attempt: 1, actor: { id: 'alice' } })
    expect(minutes[1]).toMatchObject({ seq: 2, kind: 'leg_dispatched', tier: 'technical' })
    expect(minutes[11]?.summary).toBe('The run failed while the agents were working. GitHub was unavailable. You can retry.')
  })

  it('keeps entries and frames identical after later appends, so a slice of the first n is a stable snapshot', () => {
    const tape = createTape(TEST_REGISTRY)
    tape.append(slice('success', 1, 10), 'backlog', wallTime(0))
    const minutes = [...tape.minutes()]
    const marks = [...tape.marks()]
    const frame = tape.frame(10)
    tape.append(slice('success', 11, 12), 'live', wallTime(5))
    minutes.forEach((entry, i) => expect(tape.minutes()[i]).toBe(entry))
    marks.forEach((mark, i) => expect(tape.marks()[i]).toBe(mark))
    expect(tape.frame(10)).toBe(frame)
  })
})
