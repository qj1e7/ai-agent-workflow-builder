import { describe, expect, it } from 'vitest'
import { beatMsOf, floorMsOf, readingMsOf } from './kinds'
import { REPLAY_HOLD_MS, SNAP_DEBT_MS, STALE_MS, TARGET_LAG_MS } from './director'
import { recording, renumber, slice, synthetic } from './recordings'
import { rehearse } from './testing'

const SUCCESS = recording('success')
const at = (seq: number) => SUCCESS[seq - 1]?.at ?? 0
const beat = (seq: number) => beatMsOf(SUCCESS[seq - 1]!)
const MESSAGE_5 = beat(5)

describe('live play', () => {
  it('folds a backlog silently and shows the honest counter at once', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 17, 'backlog')
    expect(show.director.shown).toBe(17)
    expect(show.director.beat).toBeNull()
    show.setRunNow(at(17) + 60_000)
    expect(show.sceneTime).toBe(at(17) + 60_000)
    expect(show.runUntil(5_000)).toEqual([])
  })

  it('plays calm live events one beat each at their full length', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 3, 'backlog')
    show.arrive(0, 4, 4)
    show.arrive(100, 5, 5)
    const beats = show.runUntilIdle()
    expect(beats.map((b) => [b.seq, b.startedAt, b.durationMs, b.entry])).toEqual([
      [4, 0, 1000, 'continuous'],
      [5, 1000, MESSAGE_5, 'continuous'],
    ])
  })

  it('plays a burst faster, in order, never under a floor, and drains to natural pace', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 3, 'backlog')
    show.arrive(0, 4, 10)
    const beats = show.runUntilIdle()
    expect(beats.map((b) => b.seq)).toEqual([4, 5, 6, 7, 8, 9, 10])
    for (const b of beats) expect(b.durationMs).toBeGreaterThanOrEqual(floorMsOf(SUCCESS[b.seq - 1]!))
    const debt = [4, 5, 6, 7, 8, 9, 10].reduce((total, seq) => total + beat(seq), 0)
    expect(debt).toBeLessThanOrEqual(SNAP_DEBT_MS)
    const rate = debt / TARGET_LAG_MS
    expect(beats[0]?.durationMs).toBe(Math.max(400, Math.round(1000 / rate)))
    expect(beats.at(-1)?.durationMs).toBe(beat(10))
    const last = beats.at(-1)!
    expect(last.startedAt + last.durationMs, 'catch-up finishes sooner than the queued choreography').toBeLessThan(debt)
  })

  it('holds a message for its reading time in live catch-up, and squeezes an arrival to its floor', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 3, 'backlog')
    const text = 'Two releases are newer than 1.2.14, so I suggest one ticket.'
    expect(text).toHaveLength(60)
    const short = synthetic('success', {
      seq: 5,
      ts: '2026-11-03T02:14:02.510Z',
      actor: { kind: 'agent', id: 'release_checker', display: 'Release checker' },
      summary: 'Release checker reported 2 new releases.',
      kind: 'agent_message',
      data: { speaker: { id: 'release_checker', display: 'Release checker' }, addressee: { kind: 'room' }, text },
    })
    const burst = [...slice('success', 4, 4), short, ...slice('success', 6, 10), ...renumber(slice('success', 12, 12), 11)]
    const debt = burst.reduce((total, event) => total + beatMsOf(event), 0)
    expect(debt, 'about twelve seconds queued, under the snap').toBeGreaterThan(12_000)
    expect(debt).toBeLessThan(SNAP_DEBT_MS)
    show.arriveEvents(0, burst)
    const beats = show.runUntilIdle()
    expect(beats.map((b) => b.seq)).toEqual([4, 5, 6, 7, 8, 9, 10, 11])
    expect(beats[0], 'the arrival is squeezed to its floor').toMatchObject({ kind: 'agent_joined', durationMs: 400 })
    expect(beats[1]?.durationMs, 'a 60-character message holds for 1200 + 25 per character').toBe(1200 + 25 * 60)
    expect(readingMsOf(text)).toBe(2700)
  })

  it("plays the demo's live arrivals without a snap and holds the finding line for its reading time", () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 3, 'backlog')
    for (const event of SUCCESS.filter((e) => e.seq >= 4 && e.seq <= 17)) show.arrive(event.at - at(1), event.seq, event.seq)
    const beats = show.runUntilIdle()
    expect(beats.map((b) => b.seq)).toEqual([4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 17])
    expect(beats.every((b) => b.entry === 'continuous'), 'nothing was skipped').toBe(true)
    const finding = beats.find((b) => b.seq === 10)
    const line = SUCCESS[9]!
    expect(finding?.durationMs).toBeGreaterThanOrEqual(line.kind === 'agent_message' ? readingMsOf(line.data.text) : Number.NaN)
    expect(finding?.durationMs).toBeGreaterThanOrEqual(2_500)
  })

  it('snaps to the last story event as a cut when far behind', () => {
    const show = rehearse('success', { start: 'edge' })
    const queued = SUCCESS.filter((e) => e.seq <= 18).reduce((total, e) => total + beatMsOf(e), 0)
    expect(queued).toBeGreaterThan(SNAP_DEBT_MS)
    show.arrive(0, 1, 18)
    const beats = show.runUntilIdle()
    expect(beats.map((b) => [b.seq, b.durationMs, b.entry])).toEqual([[18, 1800, 'cut']])
    expect(show.director.shown).toBe(18)
  })

  it('snaps when the oldest unshown live event went stale, as in a throttled background tab', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 3, 'backlog')
    show.arrive(0, 4, 7)
    expect(show.director.beat).toMatchObject({ seq: 4 })
    show.lateTick(STALE_MS + 5_000)
    expect(show.director.beat).toMatchObject({ seq: 7, entry: 'cut' })
    expect(show.runUntilIdle().map((b) => b.seq)).toEqual([4, 7])
  })

  it('folds a reconnect backlog without beats, cutting the beat in flight', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 5, 'backlog')
    show.arrive(0, 6, 6)
    show.runUntil(100)
    expect(show.director.beat?.type).toBe('event')
    show.arrive(100, 7, 17, 'backlog')
    expect(show.director.shown).toBe(17)
    expect(show.director.beat).toBeNull()
    expect(show.runUntilIdle()).toEqual([])
  })

  it('keeps receiving while paused and folds the rest on play as a replay', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 17, 'backlog')
    show.cue(0, { type: 'pause' })
    show.arrive(10, 18, 18)
    expect(show.director.shown).toBe(17)
    expect(show.director.mode.is).toBe('paused')
    expect(show.atEdge).toBe(false)
    show.cue(20, { type: 'play' })
    const beats = show.runUntilIdle()
    expect(beats.map((b) => [b.seq, b.durationMs])).toEqual([[18, 1800]])
    expect(show.director.mode.is).toBe('live')
  })

  it('ends a failure on the run failing and a rejection on the run being rejected', () => {
    const failure = rehearse('failure', { start: 'edge' })
    failure.arrive(0, 1, 3, 'backlog')
    const failureEvents = recording('failure')
    for (const event of failureEvents.filter((e) => e.seq >= 4)) failure.arrive(event.at - at(1), event.seq, event.seq)
    const failureBeats = failure.runUntilIdle()
    expect(failureBeats.map((b) => [b.seq, b.kind])).toEqual([
      [4, 'agent_joined'],
      [5, 'agent_message'],
      [6, 'agent_step_started'],
      [7, 'agent_message'],
      [8, 'agent_message'],
      [9, 'agent_message'],
      [10, 'agent_failed'],
      [12, 'run_failed'],
    ])

    const rejected = rehearse('rejected', { start: 'edge' })
    rejected.arrive(0, 1, 17, 'backlog')
    rejected.arrive(0, 18, 19)
    const beats = rejected.runUntilIdle()
    expect(beats.map((b) => b.kind)).toEqual(['approval_decided', 'run_rejected'])
  })

  it('plays a retry as one beat and the run is working again', () => {
    const show = rehearse('failure', { start: 'edge' })
    show.arrive(0, 1, 12, 'backlog')
    show.arriveSynthetic(0, {
      seq: 13,
      ts: '2026-11-04T02:20:00Z',
      actor: { kind: 'user', id: 'alice', display: 'Alice' },
      summary: 'Alice retried the run.',
      kind: 'run_retried',
      data: { leg: 'work', attempt: 2 },
    })
    const beats = show.runUntilIdle()
    expect(beats.map((b) => [b.seq, b.kind])).toEqual([[13, 'run_retried']])
    expect(show.room.phase).toEqual({ name: 'working' })
  })

  it('never counts from before the last event when the run clock lags behind it', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 17, 'backlog')
    show.setRunNow(at(17) - 60_000)
    expect(show.sceneTime).toBe(at(17))
    expect(show.waiting?.elapsedMs).toBe(at(17) - at(15))
    show.setRunNow(at(17) + 60_000)
    expect(show.sceneTime).toBe(at(17) + 60_000)
    expect(show.waiting?.elapsedMs).toBe(at(17) + 60_000 - at(15))
  })

  it('is catching up while more choreography than the target lag is queued, and not once it has drained', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 3, 'backlog')
    expect(show.catchingUp).toBe(false)
    show.arrive(0, 4, 17)
    expect(show.catchingUp).toBe(true)
    show.runUntilIdle()
    expect(show.catchingUp).toBe(false)
    expect(show.atEdge).toBe(true)
  })

  it('counts an honest wait and wakes on the next whole second', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 17, 'backlog')
    const wholeSecond = Math.ceil(at(15) / 1000) * 1000
    show.setRunNow(wholeSecond + 6 * 60_000 + 13_000)
    expect(show.waiting?.elapsedMs).toBe(wholeSecond - at(15) + 6 * 60_000 + 13_000)
    expect(show.nextWake).toBe(1000)
    show.setRunNow(wholeSecond + 6 * 60_000 + 13_400)
    expect(show.nextWake).toBe(600)
  })

  it('scrubs back to a stored frame with no beat', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 23, 'backlog')
    show.cue(0, { type: 'seek', cursor: 9 })
    expect(show.director.shown).toBe(9)
    expect(show.director.beat).toBeNull()
    expect(show.room.caption?.summary).toBe('Release checker found 2 new releases: 1.2.16, 1.2.15.')
    expect(show.atEdge).toBe(false)
    expect(show.sceneTime).toBe(at(9))
    show.cue(0, { type: 'go_live' })
    expect(show.director.shown).toBe(23)
    expect(show.atEdge).toBe(true)
  })
})

describe('replay', () => {
  it('ignores catch-up: every beat at full length, then hands back to live', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 23, 'backlog')
    show.cue(0, { type: 'seek', cursor: 3 })
    show.cue(0, { type: 'pause' })
    show.cue(0, { type: 'play' })
    const beats = show.runUntilIdle()
    expect(beats[0]).toMatchObject({ seq: 4, durationMs: 1000 })
    expect(beats.every((b) => b.durationMs === beatMsOf(SUCCESS[b.seq - 1]!))).toBe(true)
    expect(show.director.mode.is).toBe('live')
    expect(show.director.shown).toBe(23)
  })

  it('compresses the six minute wait into one hold while the counter rolls through the real time', () => {
    const show = rehearse('success', { start: 'beginning' })
    show.arrive(0, 1, 23, 'backlog')
    while (show.director.beat?.type !== 'hold') if (!show.step()) throw new Error('no hold started')
    const hold = show.director.beat
    expect(hold).toMatchObject({ after: 17, from: at(17), to: at(18), durationMs: REPLAY_HOLD_MS })
    expect(show.sceneTimeAt(hold.startedAt + REPLAY_HOLD_MS / 2)).toBe(Math.round((at(17) + at(18)) / 2))
    const beats = show.runUntilIdle()
    expect(show.holds).toHaveLength(1)
    const index = beats.findIndex((b) => b.seq === 18)
    const before = beats[index - 1]!
    expect(before.seq).toBe(17)
    expect(beats[index]!.startedAt).toBe(before.startedAt + before.durationMs + REPLAY_HOLD_MS)
    const last = beats.at(-1)!
    expect(last.startedAt + last.durationMs).toBeLessThan(30_000)
    expect(show.director.mode.is).toBe('live')
    expect(show.label).toBe('finished')
  })

  it('restarts from frame 0 with a fresh take', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 23, 'backlog')
    const take = show.director.take
    show.cue(0, { type: 'restart' })
    expect(show.director.shown).toBe(1)
    expect(show.director.beat).toMatchObject({ type: 'event', seq: 1 })
    expect(show.director.take).toBeGreaterThan(take)
    expect(show.room.phase.name).toBe('pending')
    const beats = show.runUntilIdle()
    expect(beats[0]).toMatchObject({ seq: 1, kind: 'run_created' })
  })

  it('a finished run at the edge is labelled finished and does not count', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 23, 'backlog')
    expect(show.label).toBe('finished')
    expect(show.sceneTime).toBe(at(23))
    expect(show.nextWake).toBeNull()
  })

  it('a live run at the edge is labelled live and behind the edge replay', () => {
    const show = rehearse('success', { start: 'edge' })
    show.arrive(0, 1, 17, 'backlog')
    expect(show.label).toBe('live')
    show.cue(0, { type: 'seek', cursor: 5 })
    expect(show.label).toBe('replay')
  })
})

it('plays the whole rejected recording from the start in under thirty seconds', () => {
  const show = rehearse('rejected', { start: 'beginning' })
  show.arrive(0, 1, 19, 'backlog')
  const beats = show.runUntilIdle()
  const last = beats.at(-1)!
  expect(last.startedAt + last.durationMs).toBeLessThan(30_000)
  expect(slice('rejected', 18, 19).map((e) => e.kind)).toEqual(['approval_decided', 'run_rejected'])
})
