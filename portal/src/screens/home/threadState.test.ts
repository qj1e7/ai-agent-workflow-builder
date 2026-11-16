import { describe, expect, it } from 'vitest'
import type { PlannerReply } from '../../api/types'
import { EMPTY_FORM } from './card'
import { askOf, chatOf, EMPTY, isThinking, previousOf, threadReducer } from './threadState'

const REPLY: PlannerReply = { trace_id: null, answer: 'abilities', how_to_start: false, parts: [] }

describe('the thread', () => {
  it('shows the person’s words, then the Planner thinking, then its answer in the same place', () => {
    const sent = threadReducer(EMPTY, { type: 'sent', text: 'What can you do?', chat: 'c1' })
    expect(sent.messages.map((m) => m.kind)).toEqual(['me', 'thinking'])
    expect(isThinking(sent)).toBe(true)
    const answered = threadReducer(sent, { type: 'answered', reply: REPLY, typed: 'What can you do?' })
    expect(answered.messages.map((m) => m.kind)).toEqual(['me', 'reply'])
    expect(isThinking(answered)).toBe(false)
  })

  it('takes a failed send back out, so nothing the person did not get an answer to stays in the thread', () => {
    const failed = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'x', chat: 'c1' }), { type: 'failed' })
    expect(failed.messages).toEqual([])
  })

  it('keeps earlier turns when a later one fails', () => {
    const first = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }), { type: 'answered', reply: REPLY, typed: 'a' })
    const failed = threadReducer(threadReducer(first, { type: 'sent', text: 'b', chat: 'c1' }), { type: 'failed' })
    expect(failed.messages.map((m) => m.kind)).toEqual(['me', 'reply'])
  })

  it('gives every message its own id, and New chat clears them all', () => {
    const two = threadReducer(threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }), { type: 'answered', reply: REPLY, typed: 'a' }), { type: 'sent', text: 'b', chat: 'c1' })
    expect(new Set(two.messages.map((m) => m.id)).size).toBe(4)
    expect(threadReducer(two, { type: 'new_chat' })).toEqual(EMPTY)
  })

  it('hands the next typed request the turn before it: the words, the software it named, the text it answered with, and the kind of answer it was', () => {
    const ask = (reply: PlannerReply, typed: string) => threadReducer(threadReducer(EMPTY, { type: 'sent', text: typed, chat: 'c1' }), { type: 'answered', reply, typed })
    expect(previousOf(EMPTY)).toBeNull()
    const watch = ask({ trace_id: null, answer: 'watchlist', word: 'version', software: 'FastAPI', already_listed: null, also: null, parts: [] }, 'Is there a newer FastAPI?')
    expect(previousOf(watch)).toEqual({ request: 'Is there a newer FastAPI?', software: 'FastAPI', answer: null, kind: 'watchlist', trace_id: null })
    const said = ask({ trace_id: null, answer: 'question', text: 'LangGraph is at 1.2.14.', looked_at: ['watchlist'], about_software: [], parts: [] }, 'What is the newest version of LangGraph?')
    expect(previousOf(said)).toEqual({ request: 'What is the newest version of LangGraph?', software: null, answer: 'LangGraph is at 1.2.14.', kind: 'question', trace_id: null })
    expect(previousOf(ask({ trace_id: null, answer: 'offline', why: 'trouble', message: 'x', starters: [], parts: [] }, 'x'))).toBeNull()
  })

  it('hands the next message the trace of the answer before it, so typing again soon after flags that answer', () => {
    const traced: PlannerReply = { ...REPLY, trace_id: '019a8c3e5b2f7c41a3d29e6f0b7d1c55' }
    const answered = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }), { type: 'answered', reply: traced, typed: 'a' })
    expect(previousOf(answered)?.trace_id).toBe('019a8c3e5b2f7c41a3d29e6f0b7d1c55')
    const chip = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }), { type: 'answered', reply: REPLY, typed: 'a' })
    expect(previousOf(chip)?.trace_id).toBeNull()
  })

  it('sends tapped words with the turn before, so a choice after a clarifying question says so', () => {
    expect(askOf('Redis', EMPTY)).toEqual({ text: 'Redis' })
    const clarify: PlannerReply = { trace_id: null, answer: 'reply', form: 'clarify', text: 'Which software?', choices: ['Redis', 'Kafka'], offer: null, looked_at: [], parts: [] }
    const asked = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'watch it', chat: 'c1' }), { type: 'answered', reply: clarify, typed: 'watch it' })
    expect(askOf('Redis', asked)).toEqual({ text: 'Redis', previous: { request: 'watch it', software: null, answer: 'Which software?', kind: 'reply_clarify', trace_id: null } })
  })

  it('does not hand over a request that has no answer yet', () => {
    expect(previousOf(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }))).toBeNull()
  })

  it('opens a resumed draft as a card after the conversation, keeping every turn before it', () => {
    const talked = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }), { type: 'answered', reply: REPLY, typed: 'a' })
    const resumed = threadReducer(talked, { type: 'resumed', start: { form: EMPTY_FORM, plan: null, draftId: 'drf-1', similar: null } })
    expect(resumed.messages.map((m) => m.kind)).toEqual(['me', 'reply', 'card'])
    expect(resumed.messages.at(-1)?.id).toBe(resumed.last)
    expect(resumed.last).toBeGreaterThan(talked.last)
  })

  it('answers Which software is behind? at once from the watchlist, never thinking, and never as the turn the next request follows on from', () => {
    const talked = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' }), { type: 'answered', reply: REPLY, typed: 'a' })
    const asked = threadReducer(talked, { type: 'asked_behind', text: 'Which software is behind?' })
    expect(asked.messages.map((m) => m.kind)).toEqual(['me', 'reply', 'me', 'behind'])
    expect(isThinking(asked)).toBe(false)
    expect(asked.messages.at(-1)?.id).toBe(asked.last)
    expect(previousOf(asked)).toEqual(previousOf(talked))
  })
})

describe('the turn before, for a free reply', () => {
  const free = (form: 'answer' | 'clarify' | 'cant', text: string): PlannerReply => ({ trace_id: null, answer: 'reply', form, text, choices: form === 'clarify' ? ['a', 'b'] : [], offer: null, looked_at: [], parts: [] })
  const after = (reply: PlannerReply) => previousOf(threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'hmm', chat: 'c1' }), { type: 'answered', reply, typed: 'hmm' }))

  it('sends a clarifying question as reply_clarify, with its words, so the runtime refuses a second one in a row', () => {
    expect(after(free('clarify', 'Which one?'))).toEqual({ request: 'hmm', software: null, answer: 'Which one?', kind: 'reply_clarify', trace_id: null })
  })

  it('sends an answer and a can’t as plain reply, with their words', () => {
    expect(after(free('answer', 'Type what you want.'))).toMatchObject({ answer: 'Type what you want.', kind: 'reply' })
    expect(after(free('cant', 'I can’t send email yet.'))).toMatchObject({ answer: 'I can’t send email yet.', kind: 'reply' })
  })

  it('carries no words from the fallback card', () => {
    expect(after({ trace_id: null, answer: 'didnt_follow', parts: [] })).toMatchObject({ answer: null, kind: 'didnt_follow' })
  })
})

describe('the chat a message goes in', () => {
  const fresh = (...ids: string[]) => () => ids.shift() ?? 'none left'

  it('is made with the first message and kept for every message after it', () => {
    expect(chatOf(EMPTY, fresh('c1'))).toBe('c1')
    const first = threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' })
    const answered = threadReducer(first, { type: 'answered', reply: REPLY, typed: 'a' })
    expect(chatOf(answered, fresh('c2'))).toBe('c1')
    expect(threadReducer(answered, { type: 'sent', text: 'b', chat: 'c2' }).chat).toBe('c1')
  })

  it('is a new one after New chat', () => {
    const talked = threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' })
    const cleared = threadReducer(talked, { type: 'new_chat' })
    expect(chatOf(cleared, fresh('c2'))).toBe('c2')
    expect(threadReducer(cleared, { type: 'sent', text: 'b', chat: 'c2' }).chat).toBe('c2')
  })

  it('outlives a send that failed, a resumed card and an answer read from the watchlist', () => {
    const talked = threadReducer(EMPTY, { type: 'sent', text: 'a', chat: 'c1' })
    const failed = threadReducer(talked, { type: 'failed' })
    const behind = threadReducer(failed, { type: 'asked_behind', text: 'Which software is behind?' })
    const resumed = threadReducer(behind, { type: 'resumed', start: { form: EMPTY_FORM, plan: null, draftId: 'drf-1', similar: null } })
    const arrived = threadReducer(resumed, { type: 'arrived', reply: REPLY })
    expect(arrived.chat).toBe('c1')
  })

  it('is a UUID, as the platform takes, and a different one for each new chat', () => {
    const one = chatOf(EMPTY)
    expect(one).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
    expect(chatOf(EMPTY)).not.toBe(one)
  })
})
