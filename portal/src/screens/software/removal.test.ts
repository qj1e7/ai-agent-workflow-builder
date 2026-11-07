import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { errorWords } from '../../api/errors'
import { createLatch } from '../../api/latch'
import { menuTakesEscape } from '../../shell/PersonChip'
import { changeFeedback, escapeDismisses, NO_FEEDBACK, NOTICE_ID, noticeButtons, noticeWords, pressRemove, pressUndo, pressUndoAddress, pressUseNewAddress, PROBLEM_ID, UNDO_ID, type ChangeFeedback, type FeedbackEvent, type MutateCallbacks } from './removal'

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

  it('moves focus to the notice when the software was already removed, as its row and Remove button are gone', () => {
    const h = harness()
    pressRemove(h.latch, h.send, REDIS, h.dispatch, words)
    h.answer((outcome) => outcome.onError?.(new ApiError(404, { detail: 'No such watched software' })))
    expect(NOTICE_ID).toBe('change-notice')
    expect(h.state().focusTargetId).toBe(NOTICE_ID)
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

  it('says in plain words why the platform refused, drops the Undo it can no longer do, and moves focus to the words', () => {
    const cases: [number, string][] = [
      [409, 'Could not put LangGraph back. Its repository was added again since, so it is on the list already.'],
      [404, 'Could not put LangGraph back. The platform has no record of it.'],
      [410, 'Could not put LangGraph back. It was removed more than a day ago. Add it again to keep checking it.'],
      [422, 'Could not put LangGraph back. The list is full. Remove software you no longer run, then try again.'],
    ]
    for (const [status, said] of cases) {
      const h = harness(removed)
      pressUndo(h.latch, h.send, LANGGRAPH, h.dispatch, words)
      h.answer((outcome) => outcome.onError?.(new ApiError(status, { detail: 'detail' })))
      expect(h.state(), String(status)).toEqual({ notice: null, problem: said, busy: null, focusTargetId: PROBLEM_ID })
    }
  })

  it('keeps Undo to try again when the platform had a problem or did not answer', () => {
    for (const error of [new ApiError(503, null), new TypeError('Failed to fetch')]) {
      const h = harness(removed)
      pressUndo(h.latch, h.send, LANGGRAPH, h.dispatch, words)
      h.answer((outcome) => outcome.onError?.(error))
      expect(h.state().notice).toEqual(removed.notice)
      expect(h.state().problem).toMatch(/^Could not put LangGraph back\. /)
      pressUndo(h.latch, h.send, LANGGRAPH, h.dispatch, words)
      expect(h.sent).toEqual(['sw_lang', 'sw_lang'])
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
  const on = { scheduled: true, paused: false }

  it('says what happened in plain words', () => {
    expect(noticeWords({ kind: 'removed', row: LANGGRAPH }, on)).toBe('Removed LangGraph. It won’t be checked any more.')
    expect(noticeWords({ kind: 'restored', row: LANGGRAPH }, on)).toBe('Put LangGraph back on the list.')
    expect(noticeWords({ kind: 'gone', name: 'LangGraph' }, on)).toBe('LangGraph was already removed.')
    expect(noticeWords({ kind: 'added', name: 'Redis' }, on)).toBe('Added Redis. It is checked at the next check.')
    expect(noticeWords({ kind: 'added', name: 'Redis' }, { scheduled: false, paused: false })).toBe('Added Redis. Press Check now to check it.')
  })

  it('does not point to Check now while the watchlist is paused, since the page hides it', () => {
    expect(noticeWords({ kind: 'added', name: 'Redis' }, { scheduled: true, paused: true })).toBe('Added Redis. It is checked at the next check once an Operator resumes the watchlist.')
    expect(noticeWords({ kind: 'added', name: 'Redis' }, { scheduled: false, paused: true })).toBe('Added Redis. It can be checked once an Operator resumes the watchlist.')
  })

  it('can be dismissed, and only a removal offers Undo', () => {
    expect(noticeButtons({ kind: 'removed', row: LANGGRAPH })).toEqual(['Undo', 'Dismiss'])
    for (const notice of [{ kind: 'added', name: 'Redis' }, { kind: 'restored', row: LANGGRAPH }, { kind: 'gone', name: 'LangGraph' }] as const) {
      expect(noticeButtons(notice), notice.kind).toEqual(['Dismiss'])
    }
  })

  it('goes when it is dismissed or the next change replaces it', () => {
    const added: ChangeFeedback = { ...NO_FEEDBACK, notice: { kind: 'added', name: 'Redis' } }
    expect(changeFeedback(added, { type: 'dismissed' }).notice).toBeNull()
    expect(changeFeedback(added, { type: 'removing', row: LANGGRAPH }).notice).toBeNull()
    expect(changeFeedback(added, { type: 'added', name: 'Kafka' }).notice).toEqual({ kind: 'added', name: 'Kafka' })
  })
})

describe('Escape on the Software page', () => {
  const added: ChangeFeedback = { ...NO_FEEDBACK, notice: { kind: 'added', name: 'Kafka' } }
  const on = (where: 'page' | 'dialog') => ({ closest: (selector: string) => (where === 'dialog' && selector === 'dialog' ? {} : null) })
  const escape = (target: unknown, extra: { key?: string; defaultPrevented?: boolean } = {}) => ({ key: 'Escape', defaultPrevented: false, target, ...extra })

  it('clears the notice wherever focus is on the page, such as on Add after adding, as the prototype does', () => {
    expect(escapeDismisses(escape(on('page')), added)).toBe(true)
    expect(escapeDismisses(escape(null), added)).toBe(true)
  })

  it('clears an Undo notice and an already-removed notice the same way', () => {
    expect(escapeDismisses(escape(on('page')), { ...NO_FEEDBACK, notice: { kind: 'removed', row: REDIS } })).toBe(true)
    expect(escapeDismisses(escape(on('page')), { ...NO_FEEDBACK, notice: { kind: 'gone', name: 'Redis' } })).toBe(true)
  })

  it('leaves the notice to an open dialog, such as the Teams panel, which Escape closes first', () => {
    expect(escapeDismisses(escape(on('dialog')), added)).toBe(false)
  })

  it('keeps the notice, and a waiting Undo, when the open person menu took the Escape to close itself', () => {
    const key = { key: 'Escape', defaultPrevented: false, target: on('page'), preventDefault: () => (key.defaultPrevented = true) }
    expect(menuTakesEscape(key, true)).toBe(true)
    expect(escapeDismisses(key, { ...NO_FEEDBACK, notice: { kind: 'removed', row: REDIS } })).toBe(false)
  })

  it('leaves the Escape to the page when the person menu is closed', () => {
    const key = { key: 'Escape', defaultPrevented: false, target: on('page'), preventDefault: () => (key.defaultPrevented = true) }
    expect(menuTakesEscape(key, false)).toBe(false)
    expect(escapeDismisses(key, added)).toBe(true)
  })

  it('does nothing with no notice, for another key, or when something else already used the Escape', () => {
    expect(escapeDismisses(escape(on('page')), NO_FEEDBACK)).toBe(false)
    expect(escapeDismisses(escape(on('page'), { key: 'Enter' }), added)).toBe(false)
    expect(escapeDismisses(escape(on('page'), { defaultPrevented: true }), added)).toBe(false)
  })
})

describe('resuming the watchlist', () => {
  it('says it resumed, and what checks it next', () => {
    const h = harness()
    h.dispatch({ type: 'resumed' })
    const { notice } = h.state()
    if (!notice) throw new Error('no notice')
    expect(noticeWords(notice, { scheduled: true, paused: false })).toBe('Resumed. Checks run on the schedule again.')
    expect(noticeWords(notice, { scheduled: false, paused: false })).toBe('Resumed. Press Check now to check by hand.')
    expect(noticeButtons(notice)).toEqual(['Dismiss'])
    expect(h.state().focusTargetId).toBeNull()
  })
})


describe('using the new address', () => {
  const FASTAPI = { id: 'sw_fast', name: 'FastAPI', ref: 'tiangolo/fastapi', movedTo: 'fastapi/fastapi' }

  function addressHarness(start: ChangeFeedback = NO_FEEDBACK) {
    const sent: { softwareId: string; repo: string }[] = []
    const answers: MutateCallbacks[] = []
    let state = start
    let closed = 0
    return {
      latch: createLatch(),
      sent,
      send: (body: { softwareId: string; repo: string }, outcome: MutateCallbacks) => {
        sent.push(body)
        answers.push(outcome)
      },
      dispatch: (event: FeedbackEvent) => {
        state = changeFeedback(state, event)
      },
      closed: () => closed,
      onDone: () => {
        closed += 1
      },
      answer: (settle: (outcome: MutateCallbacks) => void) => {
        const outcome = answers.at(-1)
        if (!outcome) throw new Error('nothing was sent')
        settle(outcome)
        outcome.onSettled?.()
      },
      state: () => state,
    }
  }

  it('sends the address the person saw, holds a second press, and puts focus on Undo once it is done', () => {
    const h = addressHarness()
    pressUseNewAddress(h.latch, h.send, FASTAPI, h.dispatch, words, h.onDone)
    pressUseNewAddress(h.latch, h.send, FASTAPI, h.dispatch, words, h.onDone)
    expect(h.sent).toEqual([{ softwareId: 'sw_fast', repo: 'fastapi/fastapi' }])
    expect(h.state().busy).toEqual({ id: 'sw_fast', act: 'switch' })

    h.answer((outcome) => outcome.onSuccess?.(undefined))
    expect(h.closed()).toBe(1)
    expect(h.state()).toEqual({
      notice: { kind: 'switched', row: { id: 'sw_fast', name: 'FastAPI', ref: 'tiangolo/fastapi', movedTo: 'fastapi/fastapi' }, from: 'tiangolo/fastapi', to: 'fastapi/fastapi' },
      problem: null,
      busy: null,
      focusTargetId: UNDO_ID,
    })
  })

  it('says what changed and when it is read next, and offers Undo and Dismiss', () => {
    const notice = { kind: 'switched', row: FASTAPI, from: 'tiangolo/fastapi', to: 'fastapi/fastapi' } as const
    expect(noticeWords(notice, { scheduled: true, paused: false })).toBe('FastAPI is now read from fastapi/fastapi. It is checked at the next check.')
    expect(noticeWords(notice, { scheduled: false, paused: false })).toBe('FastAPI is now read from fastapi/fastapi. Press Check now to check it.')
    expect(noticeWords(notice, { scheduled: true, paused: true })).toContain('once an Operator resumes the watchlist')
    expect(noticeButtons(notice)).toEqual(['Undo', 'Dismiss'])
  })

  it('names the platform’s refusal in plain words and moves focus to it, when GitHub’s report changed meanwhile', () => {
    const h = addressHarness()
    pressUseNewAddress(h.latch, h.send, FASTAPI, h.dispatch, words, h.onDone)
    h.answer((outcome) => outcome.onError?.(new ApiError(409, { detail: 'GitHub has not reported that address' })))
    expect(h.closed()).toBe(1)
    expect(h.state().notice).toBeNull()
    expect(h.state().problem).toContain('Could not use the new address for FastAPI.')
    expect(h.state().problem).toContain('GitHub has not reported that address at the latest check')
    expect(h.state().focusTargetId).toBe(PROBLEM_ID)
  })

  it('puts the old address back with Undo, then moves focus to the row', () => {
    const h = addressHarness()
    pressUseNewAddress(h.latch, h.send, FASTAPI, h.dispatch, words, h.onDone)
    h.answer((outcome) => outcome.onSuccess?.(undefined))
    const switched = h.state().notice
    if (switched?.kind !== 'switched') throw new Error('expected a switched notice')
    pressUndoAddress(h.latch, h.send, switched, h.dispatch, words)
    expect(h.sent.at(-1)).toEqual({ softwareId: 'sw_fast', repo: 'tiangolo/fastapi' })
    expect(h.state().busy).toEqual({ id: 'sw_fast', act: 'switchBack' })
    h.answer((outcome) => outcome.onSuccess?.(undefined))
    expect(h.state().notice).toEqual({ kind: 'switchedBack', row: switched.row, to: 'tiangolo/fastapi' })
    expect(h.state().focusTargetId).toBe('software-sw_fast')
    expect(noticeWords({ kind: 'switchedBack', row: FASTAPI, to: 'tiangolo/fastapi' }, { scheduled: true, paused: false })).toBe('Put back. FastAPI is read from tiangolo/fastapi again.')
  })

  it('says why Undo failed, a day later or when the list holds the old address already', () => {
    const switched = { kind: 'switched', row: FASTAPI, from: 'tiangolo/fastapi', to: 'fastapi/fastapi' } as const
    const late = addressHarness()
    pressUndoAddress(late.latch, late.send, switched, late.dispatch, words)
    late.answer((outcome) => outcome.onError?.(new ApiError(410, { detail: 'late' })))
    expect(late.state().problem).toBe('Could not put the old address back for FastAPI. It was changed more than a day ago.')
    const held = addressHarness()
    pressUndoAddress(held.latch, held.send, switched, held.dispatch, words)
    held.answer((outcome) => outcome.onError?.(new ApiError(409, { detail: 'held' })))
    expect(held.state().problem).toContain('The list already watches that address')
  })
})
