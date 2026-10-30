import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { errorWords } from '../../api/errors'
import { createLatch } from '../../api/latch'
import { changeFeedback, NO_FEEDBACK, noticeWords, pressRemove, pressUndo, UNDO_ID, type ChangeFeedback, type FeedbackEvent, type MutateCallbacks } from './removal'

const LANGGRAPH = { id: 'sw_lang', name: 'LangGraph' }
const REDIS = { id: 'sw_redis', name: 'Redis' }
const words = (error: unknown) => errorWords(error, 'dev')

function harness(start: ChangeFeedback = NO_FEEDBACK) {
  const sent: string[] = []
  const answers: MutateCallbacks[] = []
  let state = start
  const send = (id: string, outcome: MutateCallbacks) => {
    sent.push(id)
    answers.push(outcome)
  }
  const dispatch = (event: FeedbackEvent) => {
    state = changeFeedback(state, event)
  }
  const answer = (settle: (outcome: MutateCallbacks) => void) => {
    const outcome = answers.at(-1)
    if (!outcome) throw new Error('nothing was sent')
    settle(outcome)
    outcome.onSettled?.()
  }
  return { latch: createLatch(), sent, send, dispatch, answer, state: () => state }
}

describe('removing software', () => {
  it('sends the removal at once, holds a second press, and offers Undo with focus on it once the platform answers', () => {
    const h = harness()
    pressRemove(h.latch, h.send, LANGGRAPH, h.dispatch, words)
    expect(h.sent).toEqual(['sw_lang'])
    expect(h.state().busy).toEqual({ id: 'sw_lang', act: 'remove' })
    pressRemove(h.latch, h.send, REDIS, h.dispatch, words)
    expect(h.sent).toEqual(['sw_lang'])

    h.answer((outcome) => outcome.onSuccess?.(undefined))
    expect(h.state()).toEqual({ notice: { kind: 'removed', row: LANGGRAPH }, problem: null, busy: null, focusTargetId: UNDO_ID })
    pressRemove(h.latch, h.send, REDIS, h.dispatch, words)
    expect(h.sent).toEqual(['sw_lang', 'sw_redis'])
  })

  it('clears an earlier message when a removal starts', () => {
    const h = harness({ ...NO_FEEDBACK, notice: { kind: 'added', name: 'Redis' }, problem: 'Something went wrong.' })
    pressRemove(h.latch, h.send, LANGGRAPH, h.dispatch, words)
    expect(h.state().notice).toBeNull()
    expect(h.state().problem).toBeNull()
  })

  it('says the software was already removed when the platform no longer lists it', () => {
    const h = harness()
    pressRemove(h.latch, h.send, LANGGRAPH, h.dispatch, words)
    h.answer((outcome) => outcome.onError?.(new ApiError(404, { detail: 'No such watched software' })))
    expect(h.state().notice).toEqual({ kind: 'gone', name: 'LangGraph' })
    expect(h.state().problem).toBeNull()
  })

  it('keeps the row and says what went wrong when the removal fails', () => {
    const h = harness()
    pressRemove(h.latch, h.send, LANGGRAPH, h.dispatch, words)
    h.answer((outcome) => outcome.onError?.(new ApiError(503, null)))
    expect(h.state()).toEqual({ notice: null, problem: 'Could not remove LangGraph. The platform had a problem. Try again in a moment.', busy: null, focusTargetId: null })
  })
})

describe('Undo', () => {
  const removed: ChangeFeedback = { notice: { kind: 'removed', row: LANGGRAPH }, problem: null, busy: null, focusTargetId: null }

  it('asks the platform to put the same software back, then says so and moves focus to its row', () => {
    const h = harness(removed)
    pressUndo(h.latch, h.send, LANGGRAPH, h.dispatch, words)
    expect(h.sent).toEqual(['sw_lang'])
    expect(h.state().busy).toEqual({ id: 'sw_lang', act: 'restore' })
    pressUndo(h.latch, h.send, LANGGRAPH, h.dispatch, words)
    expect(h.sent).toEqual(['sw_lang'])
    h.answer((outcome) => outcome.onSuccess?.(undefined))
    expect(h.state()).toEqual({ notice: { kind: 'restored', row: LANGGRAPH }, problem: null, busy: null, focusTargetId: 'remove-sw_lang' })
  })

  it('says in plain words why the software could not come back, and keeps Undo', () => {
    const cases: [number, string][] = [
      [409, 'Could not put LangGraph back. Its repository was added again since, so it is on the list already.'],
      [404, 'Could not put LangGraph back. The platform has no record of it.'],
      [422, 'Could not put LangGraph back. The list is full. Remove software you no longer run, then try again.'],
      [503, 'Could not put LangGraph back. The platform had a problem. Try again in a moment.'],
    ]
    for (const [status, said] of cases) {
      const h = harness(removed)
      pressUndo(h.latch, h.send, LANGGRAPH, h.dispatch, words)
      h.answer((outcome) => outcome.onError?.(new ApiError(status, { detail: 'detail' })))
      expect(h.state().problem, String(status)).toBe(said)
      expect(h.state().notice).toEqual(removed.notice)
    }
  })

  it('has no time limit of its own: the platform puts the software back within a day of the removal, and after the day the page says so plainly', () => {
    const inside = harness(removed)
    pressUndo(inside.latch, inside.send, LANGGRAPH, inside.dispatch, words)
    inside.answer((outcome) => outcome.onSuccess?.(undefined))
    expect(inside.state().notice).toEqual({ kind: 'restored', row: LANGGRAPH })

    const late = harness(removed)
    pressUndo(late.latch, late.send, LANGGRAPH, late.dispatch, words)
    late.answer((outcome) => outcome.onError?.(new ApiError(410, { detail: 'This software was removed more than a day ago, so it can’t be put back.' })))
    expect(late.state().problem).toBe('Could not put LangGraph back. It was removed more than a day ago. Add it again to keep checking it.')
  })

  it('stays until it is dismissed or the next message replaces it', () => {
    expect(changeFeedback(removed, { type: 'dismissed' }).notice).toBeNull()
    expect(changeFeedback(removed, { type: 'added', name: 'Redis' }).notice).toEqual({ kind: 'added', name: 'Redis' })
    expect(changeFeedback({ ...removed, focusTargetId: UNDO_ID }, { type: 'added', name: 'Redis' }).focusTargetId).toBeNull()
  })
})

describe('the message after a change to the list', () => {
  it('says what happened in plain words', () => {
    expect(noticeWords({ kind: 'removed', row: LANGGRAPH }, true)).toBe('Removed LangGraph. It won’t be checked any more.')
    expect(noticeWords({ kind: 'restored', row: LANGGRAPH }, true)).toBe('Put LangGraph back on the list.')
    expect(noticeWords({ kind: 'gone', name: 'LangGraph' }, true)).toBe('LangGraph was already removed.')
    expect(noticeWords({ kind: 'added', name: 'Redis' }, true)).toBe('Added Redis. It is checked at the next check.')
    expect(noticeWords({ kind: 'added', name: 'Redis' }, false)).toBe('Added Redis. Press Check now to check it.')
  })
})
