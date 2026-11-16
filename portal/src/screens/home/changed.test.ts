import { describe, expect, it } from 'vitest'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import type { ChangedInN8nReply, PlannerReply } from '../../api/types'
import { sayOf } from './answers'
import { arrivalKey, buttonsOf, OPEN, refusedPhase, statusOf, unseenArrivals, wordsOf } from './changed'
import { EMPTY, previousOf, threadReducer } from './threadState'

const REFUSED = (aliceHome.changed_in_n8n as ChangedInN8nReply[])[0]!
const SAFE: ChangedInN8nReply = { ...REFUSED, grade: 'safe', findings: [], changes: ['Now runs every day at 7:30.'] }
const FIX: ChangedInN8nReply = { ...REFUSED, grade: 'needs_a_fix', findings: ['“Send email” is not a block we run.'] }

describe('the Changed in n8n card’s words', () => {
  it('names the workflow, its version and who published it', () => {
    expect(wordsOf(REFUSED).who).toBe('FastAPI release check, version 4, by Alice Tan.')
    expect(wordsOf(REFUSED).unknown).toBeNull()
  })

  it('says it does not know a publisher the People list could not match, and that its runs stop', () => {
    const words = wordsOf({ ...REFUSED, by: null, by_name: null })
    expect(words.who).toBe('FastAPI release check, version 4, by someone we don’t know.')
    expect(words.unknown).toBe('We don’t know who published it in n8n, so its runs stop.')
  })

  it('says what a refused write does, and names the ticket only when a change does', () => {
    expect(wordsOf(REFUSED).refused).toBe('Without a yes, our platform refuses the write. The next run stops before the write.')
    expect(wordsOf({ ...REFUSED, changes: ['Deleted “Ask for a yes” before “Create ticket”.'] }).refused).toBe('Without a yes, our platform refuses the write. The next run stops before the ticket.')
  })

  it('shows the findings only for a version that needs a fix, and the refusal only for refused writes', () => {
    expect(wordsOf(FIX)).toMatchObject({ findings: ['“Send email” is not a block we run.'], refused: null })
    expect(wordsOf(SAFE)).toMatchObject({ findings: [], refused: null })
    expect(wordsOf(REFUSED).findings).toEqual([])
  })

  it('has the Planner say the new version is checked, and that it needs a fix when it is not safe', () => {
    expect(sayOf(SAFE)).toBe('I checked the new version.')
    expect(sayOf(REFUSED)).toBe('I checked the new version. It needs a fix.')
    expect(sayOf(FIX)).toBe('I checked the new version. It needs a fix.')
  })
})

describe('the Changed in n8n card for settings saved in n8n', () => {
  const SAVED: ChangedInN8nReply = { ...FIX, made: 'settings_changed_in_n8n', by: null, by_name: null, findings: ['Its failures do not go to the platform’s error workflow.'], changes: ['Changed its settings: the error workflow.'] }

  it('says the settings changed, names nobody, and gives the checker’s reason', () => {
    const words = wordsOf(SAVED)
    expect(words.who).toBe(`${SAVED.name}, version ${SAVED.version}. Its settings were changed in n8n.`)
    expect(words.unknown).toBeNull()
    expect(words.changes).toEqual(['Changed its settings: the error workflow.'])
    expect(words.findings).toEqual(SAVED.findings)
  })

  it('offers Undo, which puts the version before back, settings and all', () => {
    expect(buttonsOf(SAVED, OPEN, true)).toEqual({ yes: false, undo: true })
  })
})

describe('the Changed in n8n card’s buttons', () => {
  it('offers Add the yes back only for refused writes, and Undo for every grade', () => {
    expect(buttonsOf(REFUSED, OPEN, true)).toEqual({ yes: true, undo: true })
    expect(buttonsOf(SAFE, OPEN, true)).toEqual({ yes: false, undo: true })
    expect(buttonsOf(FIX, OPEN, true)).toEqual({ yes: false, undo: true })
  })

  it('offers an Approver nothing', () => {
    expect(buttonsOf(REFUSED, OPEN, false)).toEqual({ yes: false, undo: false })
  })

  it('offers nothing once another version is in use', () => {
    const moved = { ...REFUSED, in_use: 5 }
    expect(buttonsOf(moved, OPEN, true)).toEqual({ yes: false, undo: false })
    expect(statusOf(moved, OPEN)).toEqual({ words: 'Version 5 is in use now.', good: false })
  })

  it('settles with the version the platform put in use, and takes the buttons away', () => {
    const settled = { kind: 'settled', version: 6 } as const
    expect(statusOf(REFUSED, settled)).toEqual({ words: 'Done. Version 6 is in use.', good: true })
    expect(buttonsOf(REFUSED, settled, true)).toEqual({ yes: false, undo: false })
  })

  it('says nothing until something happens', () => {
    expect(statusOf(REFUSED, OPEN)).toBeNull()
  })
})

describe('what the card does with a refusal', () => {
  it('shows the line and keeps the buttons when it changed again in n8n, as the sketch’s new state', () => {
    const phase = refusedPhase('Changed again since, in n8n. Nothing was saved.')
    expect(phase).toEqual({ kind: 'lost', words: 'Changed again since, in n8n. Nothing was saved.' })
    expect(buttonsOf(REFUSED, phase, true)).toEqual({ yes: true, undo: true })
  })

  it('takes the buttons away when another version is in use by now', () => {
    const phase = refusedPhase('Another version is in use by now, so nothing changed.')
    expect(buttonsOf(REFUSED, phase, true)).toEqual({ yes: false, undo: false })
  })

  it('shows any other refusal in the platform’s own words and keeps the buttons', () => {
    const phase = refusedPhase('This workflow was deleted in n8n, so it can’t change there.')
    expect(phase).toEqual({ kind: 'refused', words: 'This workflow was deleted in n8n, so it can’t change there.' })
    expect(buttonsOf(REFUSED, phase, true).undo).toBe(true)
  })
})

describe('what arrives in the chat', () => {
  const older: ChangedInN8nReply = { ...SAFE, use_case_id: 'uc_older', version: 2, in_use: 2 }

  it('arrives oldest first, because Home lists the newest first', () => {
    expect(unseenArrivals([REFUSED, older], new Set()).map(arrivalKey)).toEqual(['uc_older:2', 'uc_fastapi:4'])
  })

  it('never shows one twice', () => {
    expect(unseenArrivals([REFUSED, older], new Set(['uc_fastapi:4'])).map(arrivalKey)).toEqual(['uc_older:2'])
    expect(unseenArrivals([REFUSED], new Set(['uc_fastapi:4']))).toEqual([])
  })

  it('shows a newer version of the same workflow as its own card', () => {
    expect(unseenArrivals([{ ...REFUSED, version: 5, in_use: 5 }], new Set(['uc_fastapi:4'])).map(arrivalKey)).toEqual(['uc_fastapi:5'])
  })

  it('adds the card with no message from the person before it', () => {
    const thread = threadReducer(EMPTY, { type: 'arrived', reply: REFUSED })
    expect(thread.messages).toEqual([{ kind: 'reply', id: 1, reply: REFUSED, typed: '' }])
    expect(threadReducer(thread, { type: 'arrived', reply: SAFE }).messages.map((m) => m.id)).toEqual([1, 2])
  })

  it('lands before a request still waiting for its answer, so a failed send takes back only the request', () => {
    const asking = threadReducer(EMPTY, { type: 'sent', text: 'Check my workflows', chat: 'c1' })
    const arrived = threadReducer(asking, { type: 'arrived', reply: REFUSED })
    expect(arrived.messages.map((m) => m.kind)).toEqual(['reply', 'me', 'thinking'])
    expect(threadReducer(arrived, { type: 'failed' }).messages).toEqual([{ kind: 'reply', id: 3, reply: REFUSED, typed: '' }])
    const answered = threadReducer(arrived, { type: 'answered', reply: { trace_id: null, answer: 'abilities', how_to_start: false, parts: [] } as PlannerReply, typed: 'Check my workflows' })
    expect(answered.messages.map((m) => m.kind)).toEqual(['reply', 'me', 'reply'])
  })

  it('does not take the card for the answer a typed request follows on from', () => {
    const asked = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'Check my workflows', chat: 'c1' }), { type: 'answered', reply: { trace_id: null, answer: 'abilities', how_to_start: false, parts: [] } as PlannerReply, typed: 'Check my workflows' })
    expect(previousOf(threadReducer(asked, { type: 'arrived', reply: REFUSED }))?.request).toBe('Check my workflows')
    expect(previousOf(threadReducer(EMPTY, { type: 'arrived', reply: REFUSED }))).toBeNull()
  })

  it('sends no software after a card that came since the answer that named it, so “keep track of it” never means the software before the card', () => {
    const watch: PlannerReply = { trace_id: null, answer: 'watchlist', word: 'add', software: 'Node Js', already_listed: null, also: null, parts: [] }
    const asked = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'add Node Js', chat: 'c1' }), { type: 'answered', reply: watch, typed: 'add Node Js' })
    expect(previousOf(asked)?.software).toBe('Node Js')
    const after = previousOf(threadReducer(asked, { type: 'arrived', reply: REFUSED }))
    expect(after?.request).toBe('add Node Js')
    expect(after?.software).toBeNull()
  })
})
