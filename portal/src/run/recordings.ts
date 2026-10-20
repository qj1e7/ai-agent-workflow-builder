import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { parseEvent, type RunEvent } from '../stream/parse'
import { runId, type RunId } from './brand'

export type RecordingName = 'success' | 'failure' | 'rejected'

const RAW: Record<RecordingName, { readonly runId: RunId; readonly events: readonly unknown[] }> = {
  success: { runId: runId('run_01JB8'), events: success },
  failure: { runId: runId('run_01JB9'), events: failure },
  rejected: { runId: runId('run_01JBA'), events: rejected },
}

export function runIdOf(name: RecordingName): RunId {
  return RAW[name].runId
}

/** The recorded events of a fixture run, parsed through the real boundary. Test helper, never imported by app code. */
export function recording(name: RecordingName): RunEvent[] {
  const { runId: id, events } = RAW[name]
  return events.map((raw) => {
    const parsed = parseEvent(raw, id)
    if (!parsed.ok) throw new Error(`fixture ${name}: ${parsed.problem}`)
    return parsed.event
  })
}

/** Events with seq in [from, to], 1-based inclusive. */
export function slice(name: RecordingName, from: number, to: number): RunEvent[] {
  return recording(name).filter((event) => event.seq >= from && event.seq <= to)
}

/** A hand-made event in the recordings' voice, parsed through the boundary so the test cannot hold a shape the parser rejects. */
export function synthetic(name: RecordingName, raw: Record<string, unknown>): RunEvent {
  const parsed = parseEvent({ run_id: runIdOf(name), ...raw }, runIdOf(name))
  if (!parsed.ok) throw new Error(parsed.problem)
  return parsed.event
}

/** The same events renumbered to start at firstSeq, keeping their timestamps. */
export function renumber(events: readonly RunEvent[], firstSeq: number): RunEvent[] {
  return events.map((event, index) => ({ ...event, seq: (firstSeq + index) as RunEvent['seq'] }))
}
