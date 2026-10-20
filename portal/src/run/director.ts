import type { Ms, RunTime, WallTime } from './brand'
import { beatMsOf, floorMsOf, isStory } from './kinds'
import { isSettled } from './room'
import type { TapeReader } from './tape'
import type { Origin } from './tape'

/** The room may trail live by this much choreographed time before beats speed up. */
export const TARGET_LAG_MS: Ms = 4_000
/** More queued choreography than this snaps to the end state instead of playing it all faster. */
export const SNAP_DEBT_MS: Ms = 14_000
/**
 * An unshown live event older than this on the wall clock means the tab was throttled: snap. It exceeds
 * SNAP_DEBT_MS because a queue never holds more choreography than that in front of an event, and speech
 * beats play no faster than their reading time, so only a clock jump can age an event past it.
 */
export const STALE_MS: Ms = 16_000
/** A gap longer than this between events is a wait: a fixed segment on the scrubber, a hold in replay. */
export const LONG_GAP_MS: Ms = 30_000
/** Replay compresses a long wait to this, while the waiting counter rolls through the real duration. */
export const REPLAY_HOLD_MS: Ms = 2_400
export const COUNTER_TICK_MS: Ms = 1_000
export const ROLL_TICK_MS: Ms = 50

export type Start = 'edge' | 'beginning'

export type Mode =
  /** Follows the end of the tape. Catch-up rules apply. */
  | { readonly is: 'live' }
  /** Walks forward at choreographed pace, never compressed. Becomes live at the end of the tape. */
  | { readonly is: 'replay' }
  /** Nothing moves. The tape keeps growing underneath. */
  | { readonly is: 'paused'; readonly frozenAt: RunTime }

export type Beat =
  | {
      readonly type: 'event'
      readonly seq: number
      readonly startedAt: WallTime
      readonly durationMs: Ms
      /** cut: the frames before this beat were skipped (snap or seek), so the room crossfades in first. */
      readonly entry: 'continuous' | 'cut'
    }
  | {
      /** Replay only: a long recorded wait, compressed. The shown frame does not change; scene time rolls from..to. */
      readonly type: 'hold'
      readonly after: number
      readonly from: RunTime
      readonly to: RunTime
      readonly startedAt: WallTime
      readonly durationMs: Ms
    }

export interface Director {
  readonly mode: Mode
  /** The frame on screen (0..tape.length). During an event beat it is the beat's target frame. */
  readonly shown: number
  readonly beat: Beat | null
  /** Bumps on restart and seek, so a beat replayed for the same seq gets a fresh animation key. */
  readonly take: number
}

export type Cue =
  | { readonly type: 'grew'; readonly origin: Origin }
  | { readonly type: 'tick' }
  | { readonly type: 'play' }
  | { readonly type: 'pause' }
  | { readonly type: 'restart' }
  | { readonly type: 'seek'; readonly cursor: number }
  | { readonly type: 'go_live' }

export interface Stage {
  readonly tape: TapeReader
  readonly wall: WallTime
  readonly runNow: RunTime
}

export function startDirector(start: Start): Director {
  return { mode: start === 'edge' ? { is: 'live' } : { is: 'replay' }, shown: 0, beat: null, take: 0 }
}

function beatRunning(d: Director, wall: WallTime): boolean {
  return d.beat !== null && wall < d.beat.startedAt + d.beat.durationMs
}

function nextStory(tape: TapeReader, after: number): number | null {
  for (let seq = after + 1; seq <= tape.length; seq += 1) if (isStory(tape.event(seq))) return seq
  return null
}

function lastStory(tape: TapeReader): number | null {
  for (let seq = tape.length; seq >= 1; seq -= 1) if (isStory(tape.event(seq))) return seq
  return null
}

function queuedDebt(tape: TapeReader, after: number): Ms {
  let debt = 0
  for (let seq = after + 1; seq <= tape.length; seq += 1) debt += beatMsOf(tape.event(seq))
  return debt
}

function debt(d: Director, s: Stage): Ms {
  const remaining = d.beat ? Math.max(0, d.beat.startedAt + d.beat.durationMs - s.wall) : 0
  return remaining + queuedDebt(s.tape, d.shown)
}

function eventAt(tape: TapeReader, cursor: number): RunTime | null {
  if (cursor < 1 || cursor > tape.length) return cursor > tape.length && tape.length > 0 ? tape.event(tape.length).at : null
  return tape.event(cursor).at
}

export function settled(s: Stage): boolean {
  return s.tape.length > 0 && isSettled(s.tape.frame(s.tape.length))
}

function snap(d: Director, s: Stage): Director {
  const k = lastStory(s.tape)
  if (k === null) return { ...d, shown: s.tape.length, beat: null }
  return {
    ...d,
    shown: k,
    beat: { type: 'event', seq: k, startedAt: s.wall, durationMs: beatMsOf(s.tape.event(k)), entry: 'cut' },
  }
}

function next(d: Director, s: Stage): Director {
  const j = nextStory(s.tape, d.shown)
  if (j === null) return { ...d, shown: s.tape.length, beat: null }
  const owed = queuedDebt(s.tape, d.shown)
  const stale = s.wall - s.tape.arrival(j).at > STALE_MS
  if (owed > SNAP_DEBT_MS || stale) return snap(d, s)
  const rate = Math.max(1, owed / TARGET_LAG_MS)
  const event = s.tape.event(j)
  const durationMs = Math.max(floorMsOf(event), Math.round(beatMsOf(event) / rate))
  return { ...d, shown: j, beat: { type: 'event', seq: j, startedAt: s.wall, durationMs, entry: 'continuous' } }
}

function nextReplay(d: Director, s: Stage): Director {
  const j = nextStory(s.tape, d.shown)
  if (j === null) return s.tape.length === 0 ? d : { ...d, mode: { is: 'live' }, shown: s.tape.length, beat: null }
  const from = eventAt(s.tape, d.shown)
  const to = s.tape.event(j).at
  const held = d.beat?.type === 'hold' && d.beat.after === d.shown
  if (from !== null && to - from > LONG_GAP_MS && !held) {
    return { ...d, beat: { type: 'hold', after: d.shown, from, to, startedAt: s.wall, durationMs: REPLAY_HOLD_MS } }
  }
  return {
    ...d,
    shown: j,
    beat: { type: 'event', seq: j, startedAt: s.wall, durationMs: beatMsOf(s.tape.event(j)), entry: 'continuous' },
  }
}

function advance(d: Director, s: Stage): Director {
  switch (d.mode.is) {
    case 'live':
      return next(d, s)
    case 'replay':
      return nextReplay(d, s)
    case 'paused':
      return d
  }
}

/** Every transition of the choreographer. Pure: the same director, cue and stage give the same result. */
export function direct(d: Director, cue: Cue, s: Stage): Director {
  switch (cue.type) {
    case 'grew':
      if (d.mode.is === 'paused') return d
      if (d.mode.is === 'replay') return beatRunning(d, s.wall) ? d : nextReplay(d, s)
      if (cue.origin === 'backlog') return { ...d, shown: s.tape.length, beat: null }
      if (beatRunning(d, s.wall)) return debt(d, s) > SNAP_DEBT_MS ? snap(d, s) : d
      return next(d, s)
    case 'tick':
      if (beatRunning(d, s.wall)) return d
      return advance(d, s)
    case 'play': {
      if (d.mode.is !== 'paused') return d
      const mode: Mode = d.shown < s.tape.length ? { is: 'replay' } : { is: 'live' }
      return advance({ ...d, mode, beat: null }, s)
    }
    case 'pause':
      return { ...d, mode: { is: 'paused', frozenAt: sceneTime(d, s) }, beat: null }
    case 'restart':
      return nextReplay({ ...d, mode: { is: 'replay' }, shown: 0, beat: null, take: d.take + 1 }, s)
    case 'seek': {
      const shown = Math.max(0, Math.min(s.tape.length, cue.cursor))
      const atEdge = shown === s.tape.length
      const sought: Director = { ...d, shown, beat: null, take: d.take + 1 }
      if (d.mode.is === 'paused') {
        return { ...sought, mode: { is: 'paused', frozenAt: eventAt(s.tape, shown) ?? s.runNow } }
      }
      return { ...sought, mode: atEdge ? { is: 'live' } : { is: 'replay' } }
    }
    case 'go_live':
      return { ...d, mode: { is: 'live' }, shown: s.tape.length, beat: null, take: d.take + 1 }
  }
}

/** Following live: the viewer has not paused or scrubbed, even if beats are still catching up. */
export function atEdge(d: Director): boolean {
  return d.mode.is === 'live'
}

/** When the shell should send the next 'tick'. One timer, ever. null means nothing will change on its own. */
export function wakeAt(d: Director, s: Stage): WallTime | null {
  const candidates: number[] = []
  if (d.beat && s.wall < d.beat.startedAt + d.beat.durationMs) {
    candidates.push(d.beat.startedAt + d.beat.durationMs)
    if (d.beat.type === 'hold') candidates.push(s.wall + ROLL_TICK_MS)
  } else if (d.mode.is === 'replay' && s.tape.length > 0) {
    candidates.push(s.wall)
  }
  if (atEdge(d) && s.tape.length > 0 && !settled(s)) {
    const untilNextSecond = COUNTER_TICK_MS - (((s.runNow % COUNTER_TICK_MS) + COUNTER_TICK_MS) % COUNTER_TICK_MS)
    candidates.push(s.wall + (untilNextSecond === 0 ? COUNTER_TICK_MS : untilNextSecond))
  }
  return candidates.length === 0 ? null : (Math.min(...candidates) as WallTime)
}

/** The time every counter reads: waiting since, elapsed. One rule, so the seat, spine and scrubber agree. */
export function sceneTime(d: Director, s: Stage): RunTime {
  if (d.mode.is === 'paused') return d.mode.frozenAt
  if (d.beat?.type === 'hold' && s.wall < d.beat.startedAt + d.beat.durationMs) {
    const progress = (s.wall - d.beat.startedAt) / d.beat.durationMs
    return Math.round(d.beat.from + (d.beat.to - d.beat.from) * progress) as RunTime
  }
  if (d.mode.is === 'live' && d.shown === s.tape.length && !settled(s)) return s.runNow
  return eventAt(s.tape, d.shown) ?? s.runNow
}

export type FrameLabel = 'live' | 'replay' | 'finished'

export function labelOf(d: Director, s: Stage): FrameLabel {
  if (d.mode.is !== 'live') return 'replay'
  return settled(s) && d.shown === s.tape.length ? 'finished' : 'live'
}
