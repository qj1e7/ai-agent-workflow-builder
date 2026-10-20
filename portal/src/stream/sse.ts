export interface SseFrame {
  readonly id: string | null
  readonly event: string
  readonly data: string
}

/** Pure incremental parser over text chunks, so the feed can also notice comment lines (keep-alives). */
export interface SseParser {
  /** Returns the frames completed by this chunk. A frame split across chunks waits for its blank line. */
  push(chunk: string): SseFrame[]
}

interface Draft {
  id: string | null
  event: string | null
  data: string[]
}

const emptyDraft = (): Draft => ({ id: null, event: null, data: [] })

interface Lines {
  readonly lines: readonly string[]
  /** The unfinished line after the last line end. */
  readonly rest: string
  /** The text ended in '\r', so a '\n' at the start of the next chunk completes that CRLF and is not a line. */
  readonly afterCr: boolean
}

/** Splits complete lines off the front of `text`. A '\r' ends a line at once, so a CR-only stream never stalls. */
function takeLines(text: string, afterCr: boolean): Lines {
  const lines: string[] = []
  let start = afterCr && text.startsWith('\n') ? 1 : 0
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i]
    if (ch !== '\n' && ch !== '\r') continue
    lines.push(text.slice(start, i))
    if (ch === '\r' && text[i + 1] === '\n') i += 1
    start = i + 1
  }
  return { lines, rest: text.slice(start), afterCr: text.endsWith('\r') }
}

function readField(line: string, draft: Draft): void {
  const colon = line.indexOf(':')
  const field = colon === -1 ? line : line.slice(0, colon)
  let value = colon === -1 ? '' : line.slice(colon + 1)
  if (value.startsWith(' ')) value = value.slice(1)
  if (field === 'data') draft.data.push(value)
  else if (field === 'event') draft.event = value
  else if (field === 'id') draft.id = value
}

export function createSseParser(): SseParser {
  let rest = ''
  let afterCr = false
  let draft = emptyDraft()
  return {
    push(chunk) {
      const taken = takeLines(rest + chunk, afterCr)
      rest = taken.rest
      afterCr = taken.afterCr
      const frames: SseFrame[] = []
      for (const line of taken.lines) {
        if (line === '') {
          // The spec dispatches nothing for a blank line without data, so a bare `event:` line is dropped.
          if (draft.data.length > 0) frames.push({ id: draft.id, event: draft.event ?? 'message', data: draft.data.join('\n') })
          draft = emptyDraft()
        } else if (!line.startsWith(':')) {
          readField(line, draft)
        }
      }
      return frames
    },
  }
}

/** Decoded text chunks of a response body, one per read. Ends when the body ends or the signal aborts. */
export async function* textChunks(body: ReadableStream<Uint8Array>, signal: AbortSignal): AsyncGenerator<string> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  const cancel = () => void reader.cancel()
  if (signal.aborted) {
    cancel()
    return
  }
  signal.addEventListener('abort', cancel, { once: true })
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) return
      yield decoder.decode(value, { stream: true })
    }
  } finally {
    signal.removeEventListener('abort', cancel)
    cancel()
  }
}

/**
 * Bytes to frames: UTF-8 streaming decode, LF / CRLF / CR line ends, multi-line `data:` joined by
 * '\n', ':' comment lines ignored, `retry:` ignored, dispatch on a blank line.
 */
export async function* sseFrames(body: ReadableStream<Uint8Array>, signal: AbortSignal): AsyncGenerator<SseFrame> {
  const parser = createSseParser()
  for await (const chunk of textChunks(body, signal)) yield* parser.push(chunk)
}
