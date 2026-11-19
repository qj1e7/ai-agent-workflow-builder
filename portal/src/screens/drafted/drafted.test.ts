import { describe, expect, it } from 'vitest'
import ready from '../../../../contracts/fixtures/builder/drafted.ready.json'
import type { DraftedWorkflowView } from '../../api/types'
import { EMPTY_DESK, desksReducer } from '../home/chatState'
import { EMPTY, threadReducer } from '../home/threadState'
import { addedWords, changingWords, declinedWords, draftedPill, draftedTitle, setUpLine, settledWords, stationsOf } from './drafted'
import { stillMoving } from '../../api/draftedQueries'

describe('drafted workflow words', () => {
  it('uses the same pill words the same states have everywhere', () => {
    expect(draftedPill('drafting')?.label).toBe('Drafting')
    expect(draftedPill('draft')?.label).toBe('Draft')
    expect(draftedPill('waiting')?.label).toBe('Waiting for a yes')
    expect(draftedPill('approved')?.label).toBe('Approved')
    expect(draftedPill('declined')?.label).toBe('Declined')
    expect(draftedPill('not_drafted')).toBeNull()
  })

  it('leaves Start from the Portal out of the step line', () => {
    const labels = stationsOf((ready as DraftedWorkflowView).blocks).map((station) => station.label)
    expect(labels[0]).toBe('Every Monday')
    expect(labels).not.toContain('Start from the Portal')
  })

  it('names what the check added only when it added something', () => {
    expect(addedWords(0)).toBeNull()
    expect(addedWords(1)).toBe('Added 1 thing every workflow needs.')
    expect(addedWords(3)).toBe('Added 3 things every workflow needs.')
  })

  it('says a decline in lower case, and what an older card and the box say', () => {
    expect(declinedWords({ decided_by: 'Bob', reason: 'Not needed' } as never)).toBe('Declined by Bob: not needed. Nothing was set up.')
    expect(settledWords(1, 2)).toBe('Revision 1. Revision 2 is below.')
    expect(changingWords('Release check', 1)).toBe('Changing “Release check”, revision 1')
    expect(draftedTitle({ name: null, state: 'drafting' })).toBe('Drafting it as an n8n workflow')
  })

  it('reads an approved draft as setting up until n8n holds it', () => {
    expect(setUpLine(null).words).toBe('Setting it up in n8n.')
    expect(setUpLine({ state: 'set_up', use_case_id: 'uc', words: null })).toMatchObject({ kind: 'set_up', words: 'Set up as a draft.' })
  })

  it('keeps reading while the platform moves it, and stops once it settles', () => {
    expect(stillMoving({ state: 'drafting', set_up: null })).toBe(true)
    expect(stillMoving({ state: 'waiting', set_up: null })).toBe(true)
    expect(stillMoving({ state: 'approved', set_up: null })).toBe(true)
    expect(stillMoving({ state: 'approved', set_up: { state: 'set_up', use_case_id: 'uc', words: null } })).toBe(false)
    expect(stillMoving({ state: 'draft', set_up: null })).toBe(false)
  })
})

describe('asking for a change', () => {
  const changing = { draftedId: 'dw_1', name: 'Release check', revision: 1 }

  it('keeps change mode until a change is taken or Cancel, and ends it with the new revision’s card', () => {
    const started = desksReducer({}, { user: 'u', action: { type: 'change_start', changing } })
    expect(started['u']?.changing).toEqual(changing)
    expect(desksReducer(started, { user: 'u', action: { type: 'change_cancel' } })['u']?.changing).toBeNull()
    const done = desksReducer(started, { user: 'u', action: { type: 'changed', text: 'post at 9 instead', draftedId: 'dw_1', revision: 2 } })['u']
    expect(done?.changing).toBeNull()
    expect(done?.text).toBe('')
    expect(done?.thread.messages.map((message) => message.kind)).toEqual(['me', 'drafted'])
  })

  it('shows their words, then the next revision’s card', () => {
    const thread = threadReducer(EMPTY, { type: 'changed', text: 'post at 9 instead', draftedId: 'dw_1', revision: 2 })
    expect(thread.messages[0]).toMatchObject({ kind: 'me', text: 'post at 9 instead' })
    expect(thread.messages[1]).toMatchObject({ kind: 'drafted', draftedId: 'dw_1', revision: 2 })
  })

  it('starts a desk with no change in progress', () => {
    expect(EMPTY_DESK.changing).toBeNull()
  })
})
