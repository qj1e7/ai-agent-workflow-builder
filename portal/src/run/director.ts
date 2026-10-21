import type { Ms, RunTime, WallTime } from './brand'
import { beatMsOf, floorMsOf, isStory, type BeatEvent } from './kinds'
import { isSettled, openStep, type OpenStep } from './room'
import type { TapeReader } from './tape'
import type { Origin } from './tape'

/** The view may trail live by this much choreographed time before beats speed up. */
export const TARGET_LAG_MS: Ms = 4_000
/** More queued choreography than this snaps to the end state. Above the demo's three-message burst, which director.test.ts pins. */
export const SNAP_DEBT_MS: Ms = 20_000
/** An unshown live event older than this on the wall clock means the tab was throttled: snap. */
export const STALE_MS: Ms = SNAP_DEBT_MS + 2_000
/** A gap longer than this between events is a wait: a hold in replay. The demo platform paces its recording by it too. */
export const LONG_GAP_MS: Ms = 30_000
/** Replay compresses a long wait to this, while the waiting counter rolls through the real duration. */
export const REPLAY_HOLD_MS: Ms = 2_400
export const COUNTER_TICK_MS: Ms = 1_000
export const ROLL_TICK_MS: Ms = 50

/**
 * The viewer's speed. 1 and 2 scale beats; 'instant' shows the newest frame at once and stops only where
 * the run itself stops: a person is needed now, or the run ended.
 */
export type Speed = 1 | 2 | 'instant'

export type Start = 'edge' | 'beginning'

export type Mode =
  /** Follows the end of the tape. Catch-up rules apply. */
  | { readonly is: 'live' }
  /** Walks forward at choreographed pace, never compressed. Becomes live at the end of the tape. */
  | { readonly is: 'replay' }

export type Beat =
  | {
      readonly type: 'event'
      readonly seq: number
      readonly startedAt: WallTime
      readonly durationMs: Ms
      /** cut: the frames before this beat were skipped by a snap, so the view crossfades in first. */
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
  /** Bumps on restart and on an Instant landing, so a beat replayed for the same seq gets a fresh animation key. */
  readonly take: number
  readonly speed: Speed
}

export type Cue =
  | { readonly type: 'grew'; readonly origin: Origin }
  | { readonly type: 'tick' }
  | { readonly type: 'restart' }
  | { readonly type: 'speed'; readonly speed: Speed }

export interface Stage {
  readonly tape: TapeReader
  readonly wall: WallTime
  readonly runNow: RunTime
  /** How much faster runNow moves than the wall: 1 everywhere real, the demo's squeeze inside a long wait. */
  readonly rate: number
}

export function startDirector(start: Start, speed: Speed): Director {
  return { mode: start === 'edge' ? { is: 'live' } : { is: 'replay' }, shown: 0, beat: null, take: 0, speed }
}

/**
 * The one pacing rule. At r = 1 it is beatMs, since floorMs <= beatMs for every kind, so every 1x timing holds.
 * Speech's floor is its reading time: no speed or catch-up shortens reading below the 1x reading time.
 */
export function paced(event: BeatEvent, r: number): Ms {
  return Math.max(floorMsOf(event), Math.round(beatMsOf(event) / r))
}

/** 1 or 2. Instant never paces a beat, it lands. */
function factorOf(d: Director): number {
  return d.speed === 'instant' ? 1 : d.speed
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

/** Wall time still owed at the chosen speed, so the snap and catch-up thresholds mean the same wait at 1x and 2x. */
function debt(d: Director, s: Stage): Ms {
  const remaining = d.beat ? Math.max(0, d.beat.startedAt + d.beat.durationMs - s.wall) : 0
  return remaining + queuedDebt(s.tape, d.shown) / factorOf(d)
}

function eventAt(tape: TapeReader, cursor: number): RunTime | null {
  if (cursor < 1 || cursor > tape.length) return cursor > tape.length && tape.length > 0 ? tape.event(tape.length).at : null
  return tape.event(cursor).at
}

export function settled(s: Stage): boolean {
  return s.tape.length > 0 && isSettled(s.tape.frame(s.tape.length))
}

/**
 * The run's own now at the live edge: never before the last event, so a run clock that lags the platform
 * cannot show a counter at zero under a request that has already been posted. The last event, not the
 * latest timestamp on the tape, because an agent's clock can stamp its events hours ahead.
 */
export function liveNow(s: Stage): RunTime {
  const last = eventAt(s.tape, s.tape.length)
  return last !== null && last > s.runNow ? last : s.runNow
}

export function holding(d: Director, s: Stage): boolean {
  return d.beat?.type === 'hold' && beatRunning(d, s.wall)
}

function snap(d: Director, s: Stage): Director {
  const k = lastStory(s.tape)
  if (k === null) return { ...d, shown: s.tape.length, beat: null }
  return {
    ...d,
    shown: k,
    beat: { type: 'event', seq: k, startedAt: s.wall, durationMs: paced(s.tape.event(k), factorOf(d)), entry: 'cut' },
  }
}

/**
 * Instant: straight to the head with no beat, following live, so a run waiting for a person stays at its wait.
 * Already there, it returns the same director: the counter's tick and a repeated grew never bump the take.
 */
function land(d: Director, s: Stage): Director {
  if (d.mode.is === 'live' && d.shown === s.tape.length && d.beat === null) return d
  return { ...d, mode: { is: 'live' }, shown: s.tape.length, beat: null, take: d.take + 1 }
}

function next(d: Director, s: Stage): Director {
  const j = nextStory(s.tape, d.shown)
  if (j === null) return { ...d, shown: s.tape.length, beat: null }
  const owed = queuedDebt(s.tape, d.shown) / factorOf(d)
  const stale = s.wall - s.tape.arrival(j).at > STALE_MS
  if (owed > SNAP_DEBT_MS || stale) return snap(d, s)
  const catchUp = Math.max(1, owed / TARGET_LAG_MS)
  const durationMs = paced(s.tape.event(j), factorOf(d) * catchUp)
  return { ...d, shown: j, beat: { type: 'event', seq: j, startedAt: s.wall, durationMs, entry: 'continuous' } }
}

function nextReplay(d: Director, s: Stage): Director {
  const j = nextStory(s.tape, d.shown)
  if (j === null) return s.tape.length === 0 ? d : { ...d, mode: { is: 'live' }, shown: s.tape.length, beat: null }
  const from = eventAt(s.tape, d.shown)
  const to = s.tape.event(j).at
  const held = d.beat?.type === 'hold' && d.beat.after === d.shown
  if (from !== null && to - from > LONG_GAP_MS && !held) {
    return { ...d, beat: { type: 'hold', after: d.shown, from, to, startedAt: s.wall, durationMs: REPLAY_HOLD_MS / factorOf(d) } }
  }
  return {
    ...d,
    shown: j,
    beat: { type: 'event', seq: j, startedAt: s.wall, durationMs: paced(s.tape.event(j), factorOf(d)), entry: 'continuous' },
  }
}

function advance(d: Director, s: Stage): Director {
  if (d.speed === 'instant') return land(d, s)
  return d.mode.is === 'live' ? next(d, s) : nextReplay(d, s)
}

/** Every transition of the choreographer. Pure: the same director, cue and stage give the same result. */
export function direct(d: Director, cue: Cue, s: Stage): Director {
  switch (cue.type) {
    case 'grew':
      if (d.speed === 'instant') return land(d, s)
      if (d.mode.is === 'replay') return beatRunning(d, s.wall) ? d : nextReplay(d, s)
      if (cue.origin === 'backlog') return { ...d, shown: s.tape.length, beat: null }
      if (beatRunning(d, s.wall)) return debt(d, s) > SNAP_DEBT_MS ? snap(d, s) : d
      return next(d, s)
    case 'tick':
      if (beatRunning(d, s.wall)) return d
      return advance(d, s)
    case 'restart':
      return d.speed === 'instant' ? land(d, s) : nextReplay({ ...d, mode: { is: 'replay' }, shown: 0, beat: null, take: d.take + 1 }, s)
    case 'speed':
      // Between 1x and 2x the playing beat keeps its length, because its animations already run; the next beat takes the new speed.
      return cue.speed === 'instant' ? land({ ...d, speed: 'instant' }, s) : { ...d, speed: cue.speed }
  }
}

/** Following live, even if beats are still catching up. */
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

/** The time every counter reads: waiting since, elapsed. One rule, so every counter agrees. */
export function sceneTime(d: Director, s: Stage): RunTime {
  if (d.beat?.type === 'hold' && s.wall < d.beat.startedAt + d.beat.durationMs) {
    const progress = (s.wall - d.beat.startedAt) / d.beat.durationMs
    return Math.round(d.beat.from + (d.beat.to - d.beat.from) * progress) as RunTime
  }
  if (d.mode.is === 'live' && d.shown === s.tape.length && !settled(s)) return liveNow(s)
  return eventAt(s.tape, d.shown) ?? s.runNow
}

/**
 * How long the shown frame's open step has waited. Following live while the room catches up on a step the
 * head still holds open, the wait is ongoing and runs to now, so the counter never reads 0 s while the run
 * has waited minutes. In replay, or once the head has decided the step, the wait is the shown frame's own.
 */
export function waitElapsed(d: Director, s: Stage, open: OpenStep): Ms {
  const head = atEdge(d) && !settled(s) ? openStep(s.tape.frame(s.tape.length)) : null
  const ongoing = head !== null && head.index === open.index && head.state.since === open.state.since
  const now = ongoing ? liveNow(s) : sceneTime(d, s)
  return Math.max(0, now - open.state.since)
}
