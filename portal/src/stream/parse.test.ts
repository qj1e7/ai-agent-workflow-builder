import success from '@contracts/fixtures/runs/success.json'
import failure from '@contracts/fixtures/runs/failure.json'
import { describe, expect, it } from 'vitest'
import { runId } from './brand'
import { parseEvent, parsePage } from './parse'

const RUN = runId('run_01JB8')

function ok(raw: unknown, id = RUN) {
  const parsed = parseEvent(raw, id)
  if (!parsed.ok) throw new Error(parsed.problem)
  return parsed.event
}

describe('parseEvent', () => {
  it('reads every recorded event as its own kind, with ts as a number', () => {
    const kinds = success.map((raw) => ok(raw).kind)
    expect(kinds).toEqual(success.map((raw) => raw.kind))
    const first = ok(success[0])
    expect(first.seq).toBe(1)
    expect(first.at).toBe(Date.parse('2026-11-03T02:14:00Z'))
    expect(first.summary).toBe('Alice started a run of LangGraph releases.')
    expect(first.actor.display).toBe('Alice')
  })

  it('keeps the typed data of a known kind', () => {
    const message = ok(success[4])
    expect(message.kind).toBe('agent_message')
    if (message.kind !== 'agent_message') throw new Error('expected agent_message')
    expect(message.data.text).toMatch(/^Please check langchain-ai\/langgraph/)
    expect(message.data.addressee).toEqual({ kind: 'agent', id: 'release_checker', display: 'Release checker' })
  })

  it('makes an unknown kind opaque but keeps its seq and summary', () => {
    const event = ok({ ...success[17], seq: 18, kind: 'agent_left', data: { agent: 'release_checker' } })
    expect(event.kind).toBe('opaque')
    expect(event.seq).toBe(18)
    expect(event.summary).toBe(success[17]?.summary)
    if (event.kind === 'opaque') expect(event.declaredKind).toBe('agent_left')
  })

  it('makes a known kind with a missing required key opaque', () => {
    const event = ok({ ...success[4], data: { speaker: { id: 'room_lead', display: 'Room lead' } } })
    expect(event.kind).toBe('opaque')
  })

  it('never rejects an unexpected enum value', () => {
    const raw = failure[11]
    const event = ok({ ...raw, data: { ...(raw?.data as object), reason: 'SomethingNew' } }, runId('run_01JB9'))
    expect(event.kind).toBe('run_failed')
    if (event.kind === 'run_failed') expect(event.data.reason).toBe('SomethingNew')
  })

  it('tolerates extra keys from a newer backend', () => {
    const raw = success[0]
    const event = ok({ ...raw, data: { ...(raw?.data as object), extra: 1 }, colour: 'blue' })
    expect(event.kind).toBe('run_created')
  })

  it.each([
    ['not an object', 'not json'],
    ['a seq that is not a positive integer', { ...success[0], seq: 0 }],
    ['a fractional seq', { ...success[0], seq: 1.5 }],
    ['another run', { ...success[0], run_id: 'run_other' }],
    ['a ts that does not parse', { ...success[0], ts: 'yesterday' }],
    ['an actor without a kind', { ...success[0], actor: { id: 'alice', display: 'Alice' } }],
    ['a summary that is not a string', { ...success[0], summary: 7 }],
  ])('rejects an envelope with %s', (_name, raw) => {
    const parsed = parseEvent(raw, RUN)
    expect(parsed.ok).toBe(false)
  })
})

describe('parsePage', () => {
  it('reads a JSON page', () => {
    const page = parsePage({ events: success.slice(0, 3) }, RUN)
    expect(page.ok).toBe(true)
    if (page.ok) expect(page.events.map((event) => event.seq)).toEqual([1, 2, 3])
  })

  it('fails the whole page on one broken envelope', () => {
    const page = parsePage({ events: [success[0], { ...success[1], seq: 'two' }] }, RUN)
    expect(page.ok).toBe(false)
  })

  it('fails a page that is not an events list', () => {
    expect(parsePage({ items: [] }, RUN).ok).toBe(false)
    expect(parsePage(null, RUN).ok).toBe(false)
  })
})
