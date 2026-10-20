import type { RunEvent } from '../stream/parse'
import { agentId, doorKey, type Ms, type RunTime, type WallTime } from './brand'
import {
  direct,
  labelOf,
  sceneTime,
  startDirector,
  wakeAt,
  atEdge,
  type Beat,
  type Cue,
  type Director,
  type FrameLabel,
  type Start,
} from './director'
import { recording, synthetic, type RecordingName } from './recordings'
import { openStep, type AgentRegistry, type Move, type RoomState } from './room'
import { createTape, type Origin } from './tape'

/** The registry the tests fold with: the same three known agents as src/ui/agents.ts. */
export const TEST_REGISTRY: AgentRegistry = {
  host: { id: agentId('room_lead'), display: 'Room lead' },
  troubleshooter: { id: agentId('troubleshooter'), display: 'AI troubleshooter' },
  lookup(id) {
    if (id === 'release_checker') return { display: 'Release checker', readDoor: doorKey('github') }
    if (id === 'room_lead') return { display: 'Room lead', readDoor: null }
    if (id === 'troubleshooter') return { display: 'AI troubleshooter', readDoor: null }
    return { display: id, readDoor: null }
  },
}

export interface PlayedBeat {
  readonly seq: number
  readonly kind: RunEvent['kind']
  readonly startedAt: number
  readonly durationMs: Ms
  readonly entry: 'continuous' | 'cut'
  readonly move: Move | null
}

export interface Rehearsal {
  /** Appends recording[from..to] at this wall time and cues 'grew'. */
  arrive(wall: number, from: number, to: number, origin?: Origin): void
  arriveSynthetic(wall: number, raw: Record<string, unknown>, origin?: Origin): void
  /** Appends any events as one page at this wall time, so the director sees them all at once. */
  arriveEvents(wall: number, events: readonly RunEvent[], origin?: Origin): void
  cue(wall: number, cue: Cue): void
  /** A tick that fires late, with the wakes due before it skipped, as a throttled background tab does. */
  lateTick(wall: number): void
  /** Fires the next wake. False when nothing will change on its own. */
  step(): boolean
  /** Fires every wake up to wall, in order, and returns the beats started since the last run call. */
  runUntil(wall: number): readonly PlayedBeat[]
  /** Runs until no beat is pending and nothing unshown remains. */
  runUntilIdle(): readonly PlayedBeat[]
  /** The run timeline's now, for counters. Defaults to the last event's ts. */
  setRunNow(at: number): void
  sceneTimeAt(wall: number): number
  readonly director: Director
  readonly room: RoomState
  readonly sceneTime: RunTime
  readonly atEdge: boolean
  readonly label: FrameLabel
  readonly waiting: { readonly since: RunTime; readonly elapsedMs: Ms } | null
  readonly nextWake: number | null
  readonly holds: readonly Extract<Beat, { type: 'hold' }>[]
}

/** Drives startDirector, createTape, direct and wakeAt with integer times. No timers, no DOM. */
export function rehearse(name: RecordingName, o: { start: Start }): Rehearsal {
  const events = recording(name)
  const tape = createTape(TEST_REGISTRY)
  let director = startDirector(o.start)
  let now = 0
  let runNow: number | null = null
  const played: PlayedBeat[] = []
  const holds: Extract<Beat, { type: 'hold' }>[] = []
  let lastBeat: Beat | null = null

  const stage = (wall: number) => ({
    tape,
    wall: wall as WallTime,
    runNow: (runNow ?? (tape.length > 0 ? tape.event(tape.length).at : 0)) as RunTime,
  })

  function record(): void {
    const beat = director.beat
    if (beat === null || beat === lastBeat) return
    lastBeat = beat
    if (beat.type === 'hold') {
      holds.push(beat)
      return
    }
    played.push({
      seq: beat.seq,
      kind: tape.event(beat.seq).kind,
      startedAt: beat.startedAt,
      durationMs: beat.durationMs,
      entry: beat.entry,
      move: tape.move(beat.seq),
    })
  }

  function applyCue(wall: number, c: Cue): void {
    now = Math.max(now, wall)
    director = direct(director, c, stage(now))
    record()
  }

  /** Fires the wakes due before wall, as the store's timer would, then applies the cue. */
  function cue(wall: number, c: Cue): void {
    advanceTo(wall)
    applyCue(wall, c)
  }

  function pending(): boolean {
    if (director.beat !== null) return true
    if (director.mode.is === 'paused') return false
    for (let seq = director.shown + 1; seq <= tape.length; seq += 1) if (seq > director.shown) return true
    return false
  }

  let reported = 0
  function newBeats(): readonly PlayedBeat[] {
    const fresh = played.slice(reported)
    reported = played.length
    return fresh
  }

  function step(): boolean {
    const wake = wakeAt(director, stage(now))
    if (wake === null) return false
    applyCue(Math.max(now, wake), { type: 'tick' })
    return true
  }

  function advanceTo(wall: number): void {
    for (let guard = 0; guard < 10_000; guard += 1) {
      const wake = wakeAt(director, stage(now))
      if (wake === null || wake > wall) break
      applyCue(Math.max(now, wake), { type: 'tick' })
    }
    now = Math.max(now, wall)
  }

  function runUntil(wall: number): readonly PlayedBeat[] {
    advanceTo(wall)
    return newBeats()
  }

  function runUntilIdle(): readonly PlayedBeat[] {
    for (let guard = 0; guard < 10_000 && pending(); guard += 1) if (!step()) break
    return newBeats()
  }

  function arriveEvents(wall: number, arrived: readonly RunEvent[], origin: Origin): void {
    advanceTo(wall)
    tape.append(arrived, origin, now as WallTime)
    cue(now, { type: 'grew', origin })
  }

  return {
    arrive(wall, from, to, origin = 'live') {
      arriveEvents(wall, events.filter((e) => e.seq >= from && e.seq <= to), origin)
    },
    arriveSynthetic(wall, raw, origin = 'live') {
      arriveEvents(wall, [synthetic(name, raw)], origin)
    },
    arriveEvents(wall, arrived, origin = 'live') {
      arriveEvents(wall, arrived, origin)
    },
    cue,
    lateTick: (wall) => applyCue(wall, { type: 'tick' }),
    step,
    runUntil,
    runUntilIdle,
    setRunNow(at) {
      runNow = at
    },
    sceneTimeAt: (wall) => sceneTime(director, stage(wall)),
    get director() {
      return director
    },
    get room() {
      return tape.frame(director.shown)
    },
    get sceneTime() {
      return sceneTime(director, stage(now))
    },
    get atEdge() {
      return atEdge(director)
    },
    get label() {
      return labelOf(director, stage(now))
    },
    get waiting() {
      const open = openStep(tape.frame(director.shown))
      if (!open) return null
      return { since: open.state.since, elapsedMs: sceneTime(director, stage(now)) - open.state.since }
    },
    get nextWake() {
      const wake = wakeAt(director, stage(now))
      return wake === null ? null : wake - now
    },
    holds,
  }
}
