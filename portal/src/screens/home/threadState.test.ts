import { describe, expect, it } from 'vitest'
import type { PlannerReply } from '../../api/types'
import { EMPTY, isThinking, threadReducer } from './threadState'

const REPLY: PlannerReply = { answer: 'abilities' }

describe('the thread', () => {
  it('shows the person’s words, then the Planner thinking, then its answer in the same place', () => {
    const sent = threadReducer(EMPTY, { type: 'sent', text: 'What can you do?' })
    expect(sent.messages.map((m) => m.kind)).toEqual(['me', 'thinking'])
    expect(isThinking(sent)).toBe(true)
    const answered = threadReducer(sent, { type: 'answered', reply: REPLY, typed: 'What can you do?' })
    expect(answered.messages.map((m) => m.kind)).toEqual(['me', 'reply'])
    expect(isThinking(answered)).toBe(false)
  })

  it('takes a failed send back out, so nothing the person did not get an answer to stays in the thread', () => {
    const failed = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'x' }), { type: 'failed' })
    expect(failed.messages).toEqual([])
  })

  it('keeps earlier turns when a later one fails', () => {
    const first = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a' }), { type: 'answered', reply: REPLY, typed: 'a' })
    const failed = threadReducer(threadReducer(first, { type: 'sent', text: 'b' }), { type: 'failed' })
    expect(failed.messages.map((m) => m.kind)).toEqual(['me', 'reply'])
  })

  it('gives every message its own id, and New chat clears them all', () => {
    const two = threadReducer(threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'a' }), { type: 'answered', reply: REPLY, typed: 'a' }), { type: 'sent', text: 'b' })
    expect(new Set(two.messages.map((m) => m.id)).size).toBe(4)
    expect(threadReducer(two, { type: 'new_chat' })).toEqual(EMPTY)
  })
})
