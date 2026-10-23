import { useMemo, useState, useSyncExternalStore } from 'react'
import { useApiFetch, useRunClock } from '../api/context'
import { getDevUser } from '../api/session'
import type { BlockView } from '../api/types'
import { runFeed, type Connection, type FetchLike } from '../stream/feed'
import type { RunId } from './brand'
import { choreograph, type BeatPlan } from './choreography'
import { createClock, type Clock } from './clock'
import {
  atEdge,
  direct,
  holding,
  settled as isSettledStage,
  startDirector,
  waitElapsed,
  wakeAt,
  type Cue,
  type Speed,
  type Stage,
} from './director'
import { beatMsOf } from './kinds'
import { openStep, type AgentRegistry } from './room'
import { createTape, type MinutesEntry } from './tape'
import { trackOf, type Scene, type Track } from './track'

export interface TrackView {
  readonly track: Track
  /** The beat now playing, as acts. Null between beats and after an Instant landing. */
  readonly plan: BeatPlan | null
}

export interface Controls {
  /** Cues the director. The view also remembers the choice for this viewer. */
  setSpeed(this: void, speed: Speed): void
  /** Call after a successful POST /runs/{id}/retry: the feed reconnects now, and the events it brings back play as live. */
  reconnect(this: void): void
  restart(this: void): void
}

/** Everything a run view draws. Identity changes only when something did. */
export interface LiveView {
  readonly connection: Connection
  /** Up to the shown frame; the Minutes filter technical entries unless details are on. */
  readonly minutes: readonly MinutesEntry[]
  readonly speed: Speed
  /** Live and showing the newest frame. Approve and Decline act only here. */
  readonly atHead: boolean
  readonly controls: Controls
  /** The shown frame as a Track and the playing beat's plan. Memoised per snapshot and blocks identity. */
  track(this: void, blocks: readonly BlockView[]): TrackView
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
export function createLiveView(o: { runId: RunId; env: LiveViewEnv; whenFinished: WhenFinished; speed: Speed }): LiveViewStore {
  const { fetch, clock, registry } = o.env
  const tape = createTape(registry)
  let director = startDirector('edge', o.speed)
  let connection: Connection = { is: 'connecting' }
  let cancelTimer: (() => void) | null = null
  let feed: AbortController | null = null
  let opened = false
  // Set by reconnect(). The events a reconnect brings back arrive as a backlog, which would jump to the head
  // with no beat, so the first ones that grow the tape are cued as live and run_retried animates.
  let resumed = false
  const listeners = new Set<() => void>()
  let snapshot: LiveView | null = null

  const stage = (): Stage => ({ tape, wall: clock.wall(), runNow: clock.runNow(), rate: clock.rate() })

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

  function cue(c: Cue): void {
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
          cue({ type: 'grew', origin: resumed ? 'live' : item.origin })
          resumed = false
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
    void follow()
  }

  function stop(): void {
    feed?.abort()
    feed = null
    cancelTimer?.()
    cancelTimer = null
  }

  const controls: Controls = {
    setSpeed: (speed) => cue({ type: 'speed', speed }),
    reconnect: () => {
      resumed = true
      feed?.abort()
      feed = null
      if (listeners.size > 0) start()
    },
    restart: () => cue({ type: 'restart' }),
  }

  let minutesMemo: { shown: number; minutes: readonly MinutesEntry[] } | null = null
  function minutesUpTo(shown: number): readonly MinutesEntry[] {
    if (minutesMemo?.shown !== shown) minutesMemo = { shown, minutes: tape.minutes().slice(0, shown) }
    return minutesMemo.minutes
  }

  function build(): LiveView {
    const s = stage()
    const d = director
    const room = tape.frame(d.shown)
    const open = openStep(room)
    const scene: Scene = {
      room,
      waiting: open ? { since: open.state.since, elapsedMs: waitElapsed(d, s, open) } : null,
      spedUp: (atEdge(d) && !isSettledStage(s) && s.rate > 1) || holding(d, s),
    }
    const beat = d.beat?.type === 'event' ? d.beat : null

    function trackView(blocks: readonly BlockView[]): TrackView {
      const track = trackOf(scene, blocks)
      if (!beat) return { track, plan: null }
      const before = trackOf({ ...scene, room: tape.frame(beat.seq - 1) }, blocks)
      const timing = { key: `${d.take}:${beat.seq}`, entry: beat.entry, durationMs: beat.durationMs, baseMs: beatMsOf(tape.event(beat.seq)) }
      return { track, plan: choreograph(before, track, timing) }
    }

    let memo: { readonly blocks: readonly BlockView[]; readonly view: TrackView } | null = null
    return {
      connection,
      minutes: minutesUpTo(d.shown),
      speed: d.speed,
      atHead: d.mode.is === 'live' && d.shown === tape.length,
      controls,
      track: (blocks) => {
        if (memo?.blocks !== blocks) memo = { blocks, view: trackView(blocks) }
        return memo.view
      },
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
  /** Read once, when the store is created. Later changes go through controls.setSpeed, never a new store. */
  readonly speed: Speed
}

/**
 * The hook. The run page rests on a finished run; the overview replays it once from the start.
 * The store starts its feed on the first subscribe and stops on the last, so no effect is needed.
 */
export function useLiveView(runId: RunId, { whenFinished, registry, speed }: UseLiveViewOptions): LiveView {
  const fetchImpl = useApiFetch()
  const runClock = useRunClock()
  const [initialSpeed] = useState(speed)
  const store = useMemo(
    () =>
      createLiveView({
        runId,
        env: { fetch: withDevUser(fetchImpl), clock: createClock(runClock, runId), registry },
        whenFinished,
        speed: initialSpeed,
      }),
    [runId, fetchImpl, runClock, registry, whenFinished, initialSpeed],
  )
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
}
