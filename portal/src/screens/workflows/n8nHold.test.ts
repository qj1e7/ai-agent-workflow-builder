import held from '@contracts/fixtures/builder/use-case.n8n.held.json'
import free from '@contracts/fixtures/builder/use-case.n8n.json'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import type { UseCaseN8nView } from '../../api/types'
import { DRAFT, editorAddressOf, GONE, heldLine, NO_EDITOR, holdOf, inUseLine, mayOpen, n8nRefusalWords, openEditorTab, takenBackWords, theirsNote, type Hold } from './n8nHold'

const FREE = free as UseCaseN8nView
const HELD = held as UseCaseN8nView
const ON = { state: 'on', deleted_in_n8n_at: null } as const
const CAROL = { id: 'carol' }
const ALICE = { id: 'alice' }
const SET_PASSWORD = 'Set your n8n password first. The link is on your Settings page.'
/** 9:00 in Singapore on the day Carol opened it at 13:40. */
const SAME_DAY = new Date('2026-11-10T09:00:00Z')

describe('what the In n8n tab offers', () => {
  it('offers Open in n8n editor while nobody holds it and the person may open n8n', () => {
    const hold = holdOf(FREE, ON, ALICE)
    expect(hold).toEqual({ kind: 'free' })
    expect(mayOpen(hold)).toBe(true)
  })

  it('names the holder to themselves, with the editor’s address, and lets them open it', () => {
    const hold = holdOf(HELD, ON, CAROL)
    expect(hold).toEqual({ kind: 'mine', since: HELD.holder?.since, editorUrl: HELD.editor_url })
    expect(mayOpen(hold)).toBe(true)
  })

  it('names the holder to anyone else, who may take it back with n8n access, and never open it', () => {
    const hold = holdOf({ ...HELD, editor_url: null }, ON, ALICE)
    expect(hold).toEqual({ kind: 'theirs', name: 'Carol', since: HELD.holder?.since, cant: null })
    expect(mayOpen(hold)).toBe(false)
  })

  it('says why someone whose n8n is not ready can’t take it back either', () => {
    const hold = holdOf({ ...HELD, can_open: false, why_not: SET_PASSWORD, editor_url: null }, ON, ALICE)
    expect(hold).toMatchObject({ kind: 'theirs', cant: SET_PASSWORD })
  })

  it('draws no button for a draft, a workflow deleted in n8n, or a person n8n is closed to, and says why', () => {
    expect(holdOf(FREE, { ...ON, state: 'draft' }, ALICE)).toEqual({ kind: 'shut', words: DRAFT })
    expect(holdOf(FREE, { ...ON, deleted_in_n8n_at: '2026-11-10T05:00:00Z' }, ALICE)).toEqual({ kind: 'shut', words: GONE })
    const shut: Hold = holdOf({ ...FREE, can_open: false, why_not: SET_PASSWORD }, ON, ALICE)
    expect(shut).toEqual({ kind: 'shut', words: SET_PASSWORD })
    expect(mayOpen(shut)).toBe(false)
  })
})

describe('the In n8n tab’s words', () => {
  it('says the version in use, who published it and when, as the sketch’s “Version 4, published by Alice, just now”', () => {
    const at = '2026-11-10T05:40:00Z'
    const view = { ...FREE, version: 4, published_by_name: 'Alice', published_at: at }
    expect(inUseLine(view, false, new Date('2026-11-10T05:40:30Z'))).toBe('Version 4, published by Alice, just now')
    expect(inUseLine(view, false, new Date('2026-11-10T08:00:00Z'))).toBe('Version 4, published by Alice, today, 13:40')
    expect(inUseLine(view, false, new Date('2026-11-12T08:00:00Z'))).toBe('Version 4, published by Alice, Tue 10 Nov, 13:40')
  })

  it('says a draft was saved, not published, and never guesses a publisher nobody could be matched to', () => {
    const now = new Date('2026-11-12T08:00:00Z')
    expect(inUseLine({ ...FREE, published_at: '2026-11-10T05:40:00Z' }, true, now)).toBe('Version 1, saved as a draft by Carol, Tue 10 Nov, 13:40')
    expect(inUseLine({ ...FREE, published_by: null, published_by_name: null, published_at: '2026-11-10T05:40:00Z' }, false, now)).toBe('Version 1, published by someone we don’t know, Tue 10 Nov, 13:40')
  })

  it('says who has it open since when, in the platform’s words, and to its holder as you', () => {
    const mine = holdOf(HELD, ON, CAROL)
    const theirs = holdOf(HELD, ON, ALICE)
    if (mine.kind !== 'mine' || theirs.kind !== 'theirs') throw new Error('both are held')
    expect(heldLine(theirs, SAME_DAY)).toBe('Carol has it open in n8n since 13:40.')
    expect(heldLine(mine, SAME_DAY)).toBe('You have it open in n8n since 13:40.')
    expect(heldLine(theirs, new Date('2026-11-11T09:00:00Z')), 'a hold from another day names the day').toBe('Carol has it open in n8n since Tue 10 Nov, 13:40.')
  })

  it('makes clear that anyone with n8n access may take it back, by design', () => {
    const theirs = holdOf(HELD, ON, ALICE)
    if (theirs.kind !== 'theirs') throw new Error('held by Carol')
    expect(theirsNote(theirs)).toBe('Anyone with n8n access can take it back from Carol.')
    expect(takenBackWords(theirs)).toBe('Taken back from Carol. You can change it here again.')
  })

  it('says why the editor can’t open when the platform names no address for it', () => {
    expect(editorAddressOf({ editor_url: 'https://n8n.example/workflow/wf1' })).toEqual({ url: 'https://n8n.example/workflow/wf1' })
    expect(editorAddressOf({ editor_url: null })).toEqual({ words: NO_EDITOR })
  })

  it('shows a refusal in the platform’s own words', () => {
    const refused = new ApiError(409, { detail: 'Opening n8n is coming once the block list is on.' })
    expect(n8nRefusalWords(refused, () => 'other')).toBe('Opening n8n is coming once the block list is on.')
    expect(n8nRefusalWords(new Error('offline'), () => 'other')).toBe('other')
  })
})

describe('the tab Open in n8n editor opens', () => {
  function host(blocked = false) {
    const tab = { opener: {} as unknown, closed: false, went: null as string | null, document: { title: '', body: { textContent: '' } }, location: { replace: (url: string) => (tab.went = url) }, close: () => (tab.closed = true) }
    return { tab, open: () => (blocked ? null : (tab as unknown as Window)) }
  }

  it('opens from the press itself, cut off from the Portal at once, and goes to the editor once the platform answers', () => {
    const { tab, open } = host()
    const editor = openEditorTab({ open })
    expect(tab.opener, 'the editor never reaches back to the Portal').toBeNull()
    expect(tab.document.body.textContent).toBe('Opening n8n…')
    editor?.go('https://n8n.example/workflow/wf1')
    expect(tab.went).toBe('https://n8n.example/workflow/wf1')
  })

  it('closes the tab when the platform refuses, and gives nothing when the browser blocked it', () => {
    const { tab, open } = host()
    openEditorTab({ open })?.close()
    expect(tab.closed).toBe(true)
    expect(openEditorTab(host(true))).toBeNull()
  })
})
