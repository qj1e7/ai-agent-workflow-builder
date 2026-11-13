import { describe, expect, it } from 'vitest'
import type { PlannerReply } from '../../api/types'
import type { PanelItem } from '../../ui/sidePanel'
import { deskOf, desksReducer, EMPTY_DESK, HISTORY_MAX, panelOf, type DeskAction, type Desks } from './chatState'
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

const NEEDS: PanelItem = { kind: 'needs' }
const WORKFLOWS: PanelItem = { kind: 'workflows' }
const flow = (id: string): PanelItem => ({ kind: 'workflow', id })
const shownBy = (desks: Desks, user = 'alice') => panelOf(deskOf(desks, user).panel)

describe('the side panel’s short history', () => {
  it('starts closed, with nothing to go back to', () => {
    expect(shownBy({})).toBeNull()
  })

  it('opens one item from the chat, replacing whatever was open', () => {
    const desks = run([
      ['alice', { type: 'panel_open', item: NEEDS, from: 1 }],
      ['alice', { type: 'panel_open', item: flow('a'), from: 0 }],
    ])
    expect(shownBy(desks)).toEqual({ item: flow('a'), from: 0, previous: null })
  })

  it('keeps the list when an item opens from inside it, so Back returns to the list', () => {
    const desks = run([
      ['alice', { type: 'panel_open', item: WORKFLOWS, from: 2 }],
      ['alice', { type: 'panel_push', item: flow('a') }],
    ])
    expect(shownBy(desks)).toEqual({ item: flow('a'), from: 2, previous: WORKFLOWS })
    const back = run([['alice', { type: 'panel_back' }]], desks)
    expect(shownBy(back)).toEqual({ item: WORKFLOWS, from: 2, previous: null })
  })

  it('does not add the item it already shows, and cuts back to an item it already holds', () => {
    const base = run([
      ['alice', { type: 'panel_open', item: NEEDS, from: 0 }],
      ['alice', { type: 'panel_push', item: flow('a') }],
      ['alice', { type: 'panel_push', item: flow('a') }],
    ])
    expect(shownBy(base)?.previous).toEqual(NEEDS)
    const again = run([['alice', { type: 'panel_push', item: NEEDS }]], base)
    expect(shownBy(again)).toEqual({ item: NEEDS, from: 0, previous: null })
  })

  it('has nothing to go back to at the first item, and Back there changes nothing', () => {
    const desks = run([['alice', { type: 'panel_open', item: NEEDS, from: 0 }]])
    expect(shownBy(run([['alice', { type: 'panel_back' }]], desks))).toEqual(shownBy(desks))
  })

  it('keeps only the last few, so it stays short', () => {
    const pushes = Array.from({ length: HISTORY_MAX + 3 }, (_, i): readonly [string, DeskAction] => ['alice', { type: 'panel_push', item: flow(String(i)) }])
    const desks = run([['alice', { type: 'panel_open', item: NEEDS, from: 0 }], ...pushes])
    expect(deskOf(desks, 'alice').panel?.stack).toHaveLength(HISTORY_MAX)
    expect(shownBy(desks)?.item).toEqual(flow(String(HISTORY_MAX + 2)))
  })

  it('closes on Close and on New chat, for that person only', () => {
    const both = run([
      ['alice', { type: 'panel_open', item: NEEDS, from: 0 }],
      ['bob', { type: 'panel_open', item: WORKFLOWS, from: 0 }],
    ])
    expect(shownBy(run([['alice', { type: 'panel_close' }]], both))).toBeNull()
    expect(shownBy(run([['alice', { type: 'new_chat' }]], both))).toBeNull()
    expect(shownBy(run([['alice', { type: 'panel_close' }]], both), 'bob')?.item).toEqual(WORKFLOWS)
  })

  it('shows each person their own panel (ROLE-own-chat)', () => {
    const desks = run([['alice', { type: 'panel_open', item: NEEDS, from: 0 }]])
    expect(shownBy(desks, 'bob')).toBeNull()
  })
})
