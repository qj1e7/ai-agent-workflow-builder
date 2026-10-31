import { describe, expect, it } from 'vitest'
import { createSseParser, sseFrames, type SseFrame } from './sse'

const ACTIVITY: SseFrame = { id: '1', event: 'activity', data: '{"a":1}' }

function parseAll(chunks: readonly string[]): SseFrame[] {
  const parser = createSseParser()
  return chunks.flatMap((chunk) => parser.push(chunk))
}

describe('createSseParser', () => {
  it.each([
    ['one chunk, LF', ['id: 1\nevent: activity\ndata: {"a":1}\n\n']],
    ['a frame split mid-line across chunks', ['id: 1\nev', 'ent: activity\nda', 'ta: {"a":1}\n', '\n']],
    ['CRLF line ends', ['id: 1\r\nevent: activity\r\ndata: {"a":1}\r\n\r\n']],
    ['CR line ends', ['id: 1\revent: activity\rdata: {"a":1}\r\r']],
    ['CRLF split between chunks', ['id: 1\r', '\nevent: activity\r\ndata: {"a":1}\r', '\n\r\n']],
    ['CR split between chunks', ['id: 1\r', 'event: activity\rdata: {"a":1}\r', '\r']],
    ['comment lines between fields', [': keep-alive\nid: 1\n: hello\nevent: activity\ndata: {"a":1}\n\n']],
    ['a retry line', ['retry: 3000\nid: 1\nevent: activity\ndata: {"a":1}\n\n']],
    ['fields in another order', ['data: {"a":1}\nevent: activity\nid: 1\n\n']],
    ['a value without the space after the colon', ['id:1\nevent:activity\ndata:{"a":1}\n\n']],
  ])('parses %s to the same frame', (_name, chunks) => {
    expect(parseAll(chunks)).toEqual([ACTIVITY])
  })

  it('waits for the blank line before completing a frame', () => {
    const parser = createSseParser()
    expect(parser.push('id: 1\nevent: activity\ndata: {"a":1}\n')).toEqual([])
    expect(parser.push('\n')).toEqual([ACTIVITY])
  })

  it('joins multi-line data with a newline', () => {
    expect(parseAll(['data: first\ndata: second\n\n'])).toEqual([{ id: null, event: 'message', data: 'first\nsecond' }])
  })

  it('reports a frame without an id as id null and defaults the event name', () => {
    expect(parseAll(['data: x\n\n'])).toEqual([{ id: null, event: 'message', data: 'x' }])
  })

  it('does not carry an id over to the next frame', () => {
    expect(parseAll(['id: 1\ndata: x\n\ndata: y\n\n'])).toEqual([
      { id: '1', event: 'message', data: 'x' },
      { id: null, event: 'message', data: 'y' },
    ])
  })

  it('returns two frames from one chunk in order', () => {
    expect(parseAll(['id: 1\nevent: activity\ndata: {"a":1}\n\nid: 2\nevent: activity\ndata: {"a":2}\n\n'])).toEqual([
      ACTIVITY,
      { id: '2', event: 'activity', data: '{"a":2}' },
    ])
  })

  it('yields nothing for comments alone or a blank line with no data', () => {
    expect(parseAll([': keep-alive\n', '\n', 'event: activity\n\n', ': keep-alive\n\n'])).toEqual([])
  })

  it('keeps a colon inside the data value', () => {
    expect(parseAll(['data: {"ts":"02:14:00"}\n\n'])).toEqual([{ id: null, event: 'message', data: '{"ts":"02:14:00"}' }])
  })
})

function bytes(...chunks: readonly Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  })
}

async function collect<T>(source: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = []
  for await (const item of source) out.push(item)
  return out
}

describe('sseFrames', () => {
  it('decodes a UTF-8 character split across chunks', async () => {
    const encoded = new TextEncoder().encode('data: héllo wörld\n\n')
    const cut = encoded.indexOf(0xc3) + 1
    const frames = await collect(sseFrames(bytes(encoded.slice(0, cut), encoded.slice(cut)), new AbortController().signal))
    expect(frames).toEqual([{ id: null, event: 'message', data: 'héllo wörld' }])
  })

  it('yields the frames of a whole stream and then finishes', async () => {
    const text = 'id: 1\nevent: activity\ndata: {"a":1}\n\n: keep-alive\nid: 2\nevent: activity\ndata: {"a":2}\n\n'
    const frames = await collect(sseFrames(bytes(new TextEncoder().encode(text)), new AbortController().signal))
    expect(frames.map((frame) => frame.id)).toEqual(['1', '2'])
  })

  it('finishes when the signal aborts while the stream is open', async () => {
    let cancelled = false
    const open = new ReadableStream<Uint8Array>({ cancel: () => void (cancelled = true) })
    const controller = new AbortController()
    const pending = collect(sseFrames(open, controller.signal))
    controller.abort()
    await expect(pending).resolves.toEqual([])
    expect(cancelled).toBe(true)
  })

  it('passes a dropped connection to the caller and leaves no rejection behind', async () => {
    // A failed stream rejects cancel() with its own error, as Chromium did when platform-api restarted (P14 lane 8).
    const dropped = new TypeError('network error')
    let fail: (error: unknown) => void = () => undefined
    const open = new ReadableStream<Uint8Array>({ start: (controller) => void (fail = (error) => controller.error(error)) })
    const unhandled: unknown[] = []
    const record = (reason: unknown) => void unhandled.push(reason)
    process.on('unhandledRejection', record)
    try {
      const pending = collect(sseFrames(open, new AbortController().signal))
      fail(dropped)
      await expect(pending).rejects.toBe(dropped)
      await new Promise((resolve) => setTimeout(resolve, 0))
      expect(unhandled).toEqual([])
    } finally {
      process.off('unhandledRejection', record)
    }
  })
})
