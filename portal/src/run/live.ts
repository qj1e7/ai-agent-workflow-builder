import { useMemo, useSyncExternalStore } from 'react'
import { useApiFetch, useRunClock } from '../api/context'
import { getDevUser } from '../api/session'
import type { BlockView } from '../api/types'
import { runFeed, type Connection, type FetchLike } from '../stream/feed'
import type { Ms, RunId, RunTime, WallTime } from './brand'
import { createClock, type Clock } from './clock'
import { describeRoom } from './describe'
import {
  atEdge,
  direct,
  labelOf,
  sceneTime,
  settled as isSettledStage,
  startDirector,
  wakeAt,
  type Cue,
  type Director,
  type FrameLabel,
  type Mode,
  type Stage,
} from './director'
import { layoutRoom, type RoomLayout } from './layout'
import {
  floorPlanOf,
  openStep,
  spineStations,
  type AgentRegistry,
  type ExpectedWrite,
  type Move,
  type RoomState,
  type Station,
} from './room'
import { layoutScrubber, type ScrubberLayout } from './scrubber'
import { createTape, type MinutesEntry, type TimelineMark } from './tape'

export type BeatView =
  | {
      readonly type: 'event'
      /** Changes for every played beat, including a replay of the same seq. Components key animations on it. */
      readonly key: string
      readonly seq: number
      readonly move: Move | null
      /** The frame this beat moves away from, for a move whose subject the target frame no longer holds. */
      readonly before: RoomState
      readonly durationMs: Ms
      readonly entry: 'continuous' | 'cut'
    }
  | { readonly type: 'hold'; readonly key: string; readonly durationMs: Ms }

export interface Frame {
  readonly mode: Mode['is']
  readonly shown: number
  readonly head: number
  readonly take: number
  readonly beat: BeatView | null
  readonly label: FrameLabel
  readonly sceneTime: RunTime
  /** Present while the shown frame waits for an Approver. Honest in every mode. */
  readonly waiting: { readonly since: RunTime; readonly elapsedMs: Ms } | null
  /** "0:12 of 6:26": at = sceneTime - startedAt; total = (settled ? last event : runNow) - startedAt. */
  readonly elapsed: { readonly at: Ms; readonly total: Ms }
}

export interface Transport {
  /** Showing the newest event and following it. */
  readonly atEdge: boolean
  /** The run reached a terminal event. A settled run is never labelled live. */
  readonly settled: boolean
  readonly playing: boolean
  readonly marks: readonly TimelineMark[]
  readonly edge: { readonly now: RunTime; readonly waitingSince: RunTime | null } | null
  play(this: void): void
  pause(this: void): void
  restart(this: void): void
  seek(this: void, cursor: number): void
  backToLive(this: void): void
  /** Call after a successful POST /runs/{id}/retry, so the feed reconnects now instead of at its next check. */
  reconnect(this: void): void
}

/** Everything the room, spine, caption, Minutes and transport render. Identity changes only when something did. */
export interface LiveView {
  readonly connection: Connection
  readonly room: RoomState
  readonly frame: Frame
  /** Up to the shown frame; the component filters technical entries unless details are on. */
  readonly minutes: readonly MinutesEntry[]
  readonly transport: Transport
  /** Pure helpers bound to this snapshot, so components import nothing from the engine's internals. */
  layout(width: number, expectedWrites?: readonly ExpectedWrite[]): RoomLayout
  track(width: number): ScrubberLayout
  spine(blocks: readonly BlockView[]): readonly Station[]
  describe(): string
}

export interface LiveViewEnv {
  readonly fetch: FetchLike
  readonly clock: Clock
  readonly registry: AgentRegistry
}

export type WhenFinished = 'rest' | 'replay'

export interface LiveViewStore {
  subscribe(this: void, listener: () => void): () => void
  getSnapshot(this: void): LiveView
}

/**
 * The only imperative code in the engine. It owns one tape, one director, one timer and one feed.
 * The feed starts on the first subscriber and stops on the last, resuming from tape.length, so React
 * StrictMode's subscribe, unsubscribe, subscribe is harmless. `cue` is the only writer of the director.
 */
export function createLiveView(o: { runId: RunId; env: LiveViewEnv; whenFinished: WhenFinished; openingMs?: number }): LiveViewStore {
  const { fetch, clock, registry } = o.env
  const tape = createTape(registry)
  let director = startDirector('edge')
  let connection: Connection = { is: 'connecting' }
  let cancelTimer: (() => void) | null = null
  let feed: AbortController | null = null
  let opened = false
  const listeners = new Set<() => void>()
  let snapshot: LiveView | null = null
  // The overview's opening plays for openingMs after the first subscribe. The tape fills and a backlog
  // snaps underneath, but no beat starts until the hold ends: those cues wait and then play in order.
  let holdUntil: WallTime = clock.wall()
  let held: Cue[] = []
  let cancelHold: (() => void) | null = null

  const stage = (): Stage => ({ tape, wall: clock.wall(), runNow: clock.runNow() })

  function reschedule(): void {
    cancelTimer?.()
    cancelTimer = null
    const at = wakeAt(director, stage())
    if (at === null) return
    cancelTimer = clock.after(Math.max(0, at - clock.wall()), () => cue({ type: 'tick' }))
  }

  function publish(): void {
    snapshot = null
    for (const listener of listeners) listener()
  }

  function startsABeat(c: Cue): boolean {
    return c.type === 'tick' || c.type === 'restart' || (c.type === 'grew' && c.origin === 'live')
  }

  function cue(c: Cue): void {
    const wait = holdUntil - clock.wall()
    if (wait > 0 && startsABeat(c)) {
      held.push(c)
      cancelHold ??= clock.after(wait, () => {
        cancelHold = null
        const queued = held
        held = []
        for (const later of queued) cue(later)
      })
      publish()
      return
    }
    director = direct(director, c, stage())
    reschedule()
    publish()
  }

  async function follow(): Promise<void> {
    const controller = new AbortController()
    feed = controller
    try {
      for await (const item of runFeed({ runId: o.runId, fetch, clock, after: tape.length, signal: controller.signal })) {
        if (controller.signal.aborted) return
        if (item.type === 'connection') {
          connection = item.connection
          publish()
        } else if (item.type === 'server_time') {
          clock.setOffset(item.offsetMs)
        } else {
          const before = tape.length
          const grew = tape.append(item.events, item.origin, clock.wall()) > before
          if (!grew) continue
          cue({ type: 'grew', origin: item.origin })
          if (!opened && item.origin === 'backlog') {
            opened = true
            if (o.whenFinished === 'replay' && isSettledStage(stage())) cue({ type: 'restart' })
          }
        }
      }
    } finally {
      if (feed === controller) feed = null
    }
  }

  function start(): void {
    if (feed) return
    holdUntil = (clock.wall() + (o.openingMs ?? 0)) as WallTime
    void follow()
  }

  function stop(): void {
    feed?.abort()
    feed = null
    cancelTimer?.()
    cancelTimer = null
    cancelHold?.()
    cancelHold = null
    held = []
  }

  const transportActions = {
    play: () => cue({ type: 'play' }),
    pause: () => cue({ type: 'pause' }),
    restart: () => cue({ type: 'restart' }),
    seek: (cursor: number) => cue({ type: 'seek', cursor }),
    backToLive: () => cue({ type: 'go_live' }),
    reconnect: () => {
      feed?.abort()
      feed = null
      if (listeners.size > 0) start()
    },
  }

  let minutesMemo: { shown: number; minutes: readonly MinutesEntry[] } | null = null
  function minutesUpTo(shown: number): readonly MinutesEntry[] {
    if (minutesMemo?.shown !== shown) minutesMemo = { shown, minutes: tape.minutes().slice(0, shown) }
    return minutesMemo.minutes
  }

  function beatView(d: Director): BeatView | null {
    if (!d.beat) return null
    if (d.beat.type === 'hold') return { type: 'hold', key: `${d.take}:hold:${d.beat.after}`, durationMs: d.beat.durationMs }
    return {
      type: 'event',
      key: `${d.take}:${d.beat.seq}`,
      seq: d.beat.seq,
      move: tape.move(d.beat.seq),
      before: tape.frame(d.beat.seq - 1),
      durationMs: d.beat.durationMs,
      entry: d.beat.entry,
    }
  }

  function build(): LiveView {
    const s = stage()
    const d = director
    const room = tape.frame(d.shown)
    const now = sceneTime(d, s)
    const settled = isSettledStage(s)
    const edge = atEdge(d)
    const open = openStep(room)
    const startedAt = room.startedAt ?? (tape.length > 0 ? tape.event(1).at : now)
    const latest = tape.latestAt() ?? now
    const end = settled ? latest : Math.max(s.runNow, latest)
    const frame: Frame = {
      mode: d.mode.is,
      shown: d.shown,
      head: tape.length,
      take: d.take,
      beat: beatView(d),
      label: labelOf(d, s),
      sceneTime: now,
      waiting: open ? { since: open.state.since, elapsedMs: Math.max(0, now - open.state.since) } : null,
      elapsed: { at: Math.max(0, now - startedAt), total: Math.max(0, end - startedAt) },
    }
    const marks = tape.marks()
    const transport: Transport = {
      ...transportActions,
      atEdge: edge,
      settled,
      playing: d.mode.is !== 'paused',
      marks,
      edge: edge && !settled ? { now: s.runNow, waitingSince: open?.state.since ?? null } : null,
    }
    return {
      connection,
      room,
      frame,
      minutes: minutesUpTo(d.shown),
      transport,
      layout: (width, expectedWrites = []) => layoutRoom(floorPlanOf(room, expectedWrites), width),
      track: (width) => layoutScrubber({ marks, width, edge: transport.edge }),
      spine: (blocks) => spineStations(room, blocks),
      describe: () => describeRoom(room, now),
    }
  }

  return {
    subscribe(listener) {
      listeners.add(listener)
      if (listeners.size === 1) {
        start()
        reschedule()
      }
      return () => {
        listeners.delete(listener)
        if (listeners.size === 0) stop()
      }
    },
    getSnapshot() {
      snapshot ??= build()
      return snapshot
    },
  }
}

function withDevUser(fetchImpl: typeof fetch): FetchLike {
  return (input, init) => {
    const headers = new Headers(init?.headers)
    headers.set('X-Dev-User', getDevUser())
    return fetchImpl(input, { ...init, headers })
  }
}

export interface UseLiveViewOptions {
  readonly whenFinished: WhenFinished
  readonly registry: AgentRegistry
  /** How long the overview's opening plays before the first beat. 0 everywhere else. */
  readonly openingMs?: number
}

/**
 * The hook. The run page rests on a finished run; the overview replays it once from the start.
 * The store starts its feed on the first subscribe and stops on the last, so no effect is needed.
 */
export function useLiveView(runId: RunId, { whenFinished, registry, openingMs = 0 }: UseLiveViewOptions): LiveView {
  const fetchImpl = useApiFetch()
  const runClock = useRunClock()
  const store = useMemo(
    () =>
      createLiveView({
        runId,
        env: { fetch: withDevUser(fetchImpl), clock: createClock(runClock, runId), registry },
        whenFinished,
        openingMs,
      }),
    [runId, fetchImpl, runClock, registry, whenFinished, openingMs],
  )
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
}
