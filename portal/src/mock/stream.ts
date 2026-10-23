import type { ActivityEvent } from '../api/types'
import type { Timeline } from './timeline'

const encoder = new TextEncoder()
/** The real stream sends a comment every 15 s while idle, so the Portal can tell silence from a dead socket. */
export const KEEP_ALIVE_MS = 15_000
const keepAlive = encoder.encode(': keep-alive\n\n')

export function frame(event: ActivityEvent): Uint8Array {
  return encoder.encode(`id: ${event.seq}\nevent: activity\ndata: ${JSON.stringify(event)}\n\n`)
}

export function streamEvents(timeline: Timeline, after: number, signal: AbortSignal | null): Response {
  let cursor = after
  let timer: ReturnType<typeof setTimeout> | undefined
  let pulse: ReturnType<typeof setTimeout> | undefined
  let unsubscribe: () => void = () => undefined
  let closed = false
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined

  function stop(): void {
    closed = true
    clearTimeout(timer)
    clearTimeout(pulse)
    unsubscribe()
    signal?.removeEventListener('abort', finish)
  }

  function breathe(): void {
    clearTimeout(pulse)
    if (closed) return
    pulse = setTimeout(() => {
      if (closed || !controller) return
      controller.enqueue(keepAlive)
      breathe()
    }, KEEP_ALIVE_MS)
  }

  function finish(): void {
    if (closed) return
    stop()
    controller?.close()
  }

  function flush(): void {
    clearTimeout(timer)
    if (closed || !controller) return
    const wall = Date.now()
    for (const event of timeline.emitted(wall)) {
      if (event.seq <= cursor) continue
      controller.enqueue(frame(event))
      cursor = event.seq
    }
    const due = timeline.nextDue(wall)
    if (due !== undefined) timer = setTimeout(flush, due - wall)
    breathe()
  }

  const body = new ReadableStream<Uint8Array>({
    start(streamController) {
      controller = streamController
      if (signal?.aborted) return finish()
      signal?.addEventListener('abort', finish, { once: true })
      unsubscribe = timeline.subscribe(flush)
      flush()
    },
    cancel: stop,
  })
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
  })
}
