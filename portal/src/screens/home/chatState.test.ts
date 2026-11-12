import { describe, expect, it } from 'vitest'
import type { PlannerReply } from '../../api/types'
import { deskOf, desksReducer, EMPTY_DESK, type DeskAction, type Desks } from './chatState'
import { isThinking } from './threadState'

const REPLY: PlannerReply = { answer: 'abilities', parts: [] }

const run = (actions: readonly (readonly [string, DeskAction])[], from: Desks = {}): Desks => actions.reduce((desks, [user, action]) => desksReducer(desks, { user, action }), from)

describe('the chat each person keeps', () => {
  it('starts every person with an empty chat', () => {
    expect(deskOf({}, 'alice')).toBe(EMPTY_DESK)
  })

  it('keeps the conversation while the person is elsewhere, because nothing but the person’s own actions changes it', () => {
    const desks = run([
      ['alice', { type: 'sent', text: 'Check my workflows' }],
      ['alice', { type: 'answered', reply: REPLY, typed: 'Check my workflows' }],
    ])
    expect(deskOf(desks, 'alice').thread.messages.map((m) => m.kind)).toEqual(['me', 'reply'])
    expect(deskOf(desks, 'alice')).toBe(deskOf(run([], desks), 'alice'))
  })

  it('never shows one person’s chat to another, and gives it back when the first comes back (ROLE-own-chat)', () => {
    const asAlice = run([
      ['alice', { type: 'sent', text: 'Check my workflows' }],
      ['alice', { type: 'answered', reply: REPLY, typed: 'Check my workflows' }],
    ])
    expect(deskOf(asAlice, 'bob').thread.messages).toEqual([])
    const asBob = run([['bob', { type: 'sent', text: 'What did I decide before?' }]], asAlice)
    expect(deskOf(asBob, 'bob').thread.messages.map((m) => m.kind === 'me' && m.text)).toEqual(['What did I decide before?', false])
    expect(deskOf(asBob, 'alice').thread.messages.map((m) => m.kind === 'me' && m.text)).toEqual(['Check my workflows', false])
  })

  it('puts an answer in the chat of the person who asked, even when someone else is signed in by the time it arrives', () => {
    const desks = run([
      ['alice', { type: 'sent', text: 'Check my workflows' }],
      ['bob', { type: 'typed', text: 'hello' }],
      ['alice', { type: 'answered', reply: REPLY, typed: 'Check my workflows' }],
    ])
    expect(isThinking(deskOf(desks, 'alice').thread)).toBe(false)
    expect(deskOf(desks, 'bob').thread.messages).toEqual([])
    expect(deskOf(desks, 'bob').text).toBe('hello')
  })

  it('empties the box when a message is sent, and puts the words back when the send fails', () => {
    const sent = run([
      ['alice', { type: 'typed', text: 'Watch Redis' }],
      ['alice', { type: 'sent', text: 'Watch Redis' }],
    ])
    expect(deskOf(sent, 'alice').text).toBe('')
    const failed = run(
      [
        ['alice', { type: 'failed' }],
        ['alice', { type: 'typed', text: 'Watch Redis' }],
        ['alice', { type: 'problem', problem: 'That didn’t send. Try again.' }],
      ],
      sent,
    )
    expect(deskOf(failed, 'alice')).toMatchObject({ text: 'Watch Redis', problem: 'That didn’t send. Try again.' })
    expect(deskOf(failed, 'alice').thread.messages).toEqual([])
  })

  it('clears only that person’s chat on New chat, and leaves a note for them to read once', () => {
    const both = run([
      ['alice', { type: 'sent', text: 'a' }],
      ['bob', { type: 'sent', text: 'b' }],
    ])
    const cleared = run(
      [
        ['alice', { type: 'new_chat' }],
        ['alice', { type: 'note', text: 'Your draft is saved. Find it on Workflows.' }],
      ],
      both,
    )
    expect(deskOf(cleared, 'alice').thread.messages).toEqual([])
    expect(deskOf(cleared, 'alice').note?.text).toBe('Your draft is saved. Find it on Workflows.')
    expect(deskOf(cleared, 'bob').thread.messages).toHaveLength(2)
    expect(deskOf(run([['alice', { type: 'note_read' }]], cleared), 'alice').note).toBeNull()
  })

  it('shows a repeated note afresh, with a new id', () => {
    const once = run([['alice', { type: 'note', text: 'x' }]])
    const twice = run([['alice', { type: 'note', text: 'x' }]], once)
    expect(deskOf(twice, 'alice').note?.id).toBeGreaterThan(deskOf(once, 'alice').note?.id ?? 0)
  })
})
