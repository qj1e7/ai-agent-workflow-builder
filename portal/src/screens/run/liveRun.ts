import { useState, useSyncExternalStore } from 'react'
import { useApiFetch } from '../../api/context'
import { motionAllowed } from '../../ui/motion'
import { runId as asRunId } from '../../stream/brand'
import { runFeed, type Connection, type FeedClock, type FetchLike, type Origin } from '../../stream/feed'
import type { RunEvent } from '../../stream/parse'
import { emptyModel, fold, sameSpot, type RunModel } from './runModel'

export const MOVE_MS = 260
export const SMALL_MS = 200

export interface LiveRun {
  /** What the page draws. Live events reach it one beat at a time. */
  readonly shown: RunModel
  /** Every event the feed has brought. */
  readonly head: RunModel
  readonly connection: Connection
  /** Events up to here were drawn without motion, because they happened before the page was watching. */
  readonly loadedUpTo: number
  readonly loaded: boolean
}

export interface LiveRunEnv {
  readonly fetch: FetchLike
  readonly clock: FeedClock
  readonly paced: () => boolean
}

export interface LiveRunStore {
  subscribe(this: void, listener: () => void): () => void
  getSnapshot(this: void): LiveRun
  /** After a retry: reconnect now, and play what comes back as live. */
  restart(this: void): void
  tryAgain(this: void): void
}

/** How long the next event waits after this one. */
export function beatAfter(before: RunModel, after: RunModel): number {
  if (!sameSpot(before.spot, after.spot) || before.phase.state !== after.phase.state) return MOVE_MS + SMALL_MS
  if (after.chat !== before.chat) return SMALL_MS + 100
  return 0
}

/**
 * One store per run. The feed starts with the first subscriber and stops with the last, resuming from the events
 * already held, so React's StrictMode subscribe, unsubscribe, subscribe costs one aborted request.
 */
export function createLiveRun(id: string, env: LiveRunEnv): LiveRunStore {
  const runId = asRunId(id)
  let head = emptyModel
  let shown = emptyModel
  let connection: Connection = { is: 'connecting' }
  let loadedUpTo = 0
  let loaded = false
  let playNextAsLive = false
  let readyAt = 0
  const queue: RunEvent[] = []
  let cancelBeat: (() => void) | null = null
  let feed: AbortController | null = null
  const listeners = new Set<() => void>()
  let snapshot: LiveRun = { shown, head, connection, loadedUpTo, loaded }

  function publish(): void {
    snapshot = { shown, head, connection, loadedUpTo, loaded }
    for (const listener of listeners) listener()
  }

  function play(): void {
    cancelBeat = null
    for (let event = queue[0]; event; event = queue[0]) {
      const now = env.clock.epochNow()
      if (now < readyAt) {
        cancelBeat = env.clock.after(readyAt - now, play)
        break
      }
      queue.shift()
      const before = shown
      shown = fold(shown, event)
      readyAt = env.paced() ? now + beatAfter(before, shown) : now
    }
    publish()
  }

  function take(events: readonly RunEvent[], origin: Origin): void {
    const from = head.seq
    for (const event of events) head = fold(head, event)
    if (head.seq === from) return
    loaded = true
    if (origin === 'backlog' && !playNextAsLive) {
      cancelBeat?.()
      cancelBeat = null
      queue.length = 0
      shown = head
      loadedUpTo = head.seq
      publish()
      return
    }
    playNextAsLive = false
    queue.push(...events.filter((event) => event.seq > from))
    if (cancelBeat) publish()
    else play()
  }

  async function follow(controller: AbortController): Promise<void> {
    for await (const item of runFeed({ runId, fetch: env.fetch, clock: env.clock, after: head.seq, signal: controller.signal })) {
      if (controller.signal.aborted) return
      if (item.type === 'connection') {
        connection = item.connection
        publish()
      } else if (item.type === 'events') {
        take(item.events, item.origin)
      }
    }
  }

  function start(): void {
    if (feed) return
    const controller = new AbortController()
    feed = controller
    follow(controller)
      .catch(() => {
        connection = { is: 'closed', status: 0, reason: 'rejected' }
        publish()
      })
      .finally(() => {
        if (feed === controller) feed = null
      })
    if (queue.length > 0 && !cancelBeat) play()
  }

  function reconnect(): void {
    feed?.abort()
    feed = null
    if (listeners.size > 0) start()
  }

  function stop(): void {
    feed?.abort()
    feed = null
    cancelBeat?.()
    cancelBeat = null
  }

  return {
    subscribe(listener) {
      listeners.add(listener)
      if (listeners.size === 1) start()
      return () => {
        listeners.delete(listener)
        if (listeners.size === 0) stop()
      }
    },
    getSnapshot: () => snapshot,
    restart() {
      playNextAsLive = true
      reconnect()
    },
    tryAgain: reconnect,
  }
}

const browserClock: FeedClock = {
  after(ms, fn) {
    const timer = setTimeout(fn, ms)
    return () => clearTimeout(timer)
  },
  epochNow: () => Date.now(),
}

export function useLiveRun(runId: string): { live: LiveRun; restart: () => void; tryAgain: () => void } {
  const fetch = useApiFetch()
  const [store] = useState(() => createLiveRun(runId, { fetch, clock: browserClock, paced: motionAllowed }))
  const live = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
  return { live, restart: store.restart, tryAgain: store.tryAgain }
}
