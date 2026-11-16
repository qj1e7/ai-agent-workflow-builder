import { describe, expect, it } from 'vitest'
import editCant from '../../../../contracts/fixtures/planner/answer.edit.cant.json'
import editUnclear from '../../../../contracts/fixtures/planner/answer.edit.unclear.json'
import type { PartView, PlannerReply } from '../../api/types'
import { askOfCross, crossWords, leftoverParts, partMark } from './parts'

const crossed = (text: string, reason: PartView['reason']): PartView => ({ text, mark: 'cant', reason, note: null, choices: [] })

describe('the edit answer’s parts', () => {
  it('words a change other than when it runs, and a schedule it can’t hold, in the spec’s words', () => {
    expect(crossWords(crossed('Pause the morning check', 'only_schedule'))).toBe('From the chat I can only change when it runs.')
    expect(crossWords(crossed('monthly', 'how_often'))).toBe('I can’t run things monthly yet.')
  })

  it('names the workflow in a change it can’t make, once the card knows which', () => {
    expect(crossWords(crossed('Pause the morning check', 'only_schedule'), { workflow: 'Morning new-ticket check' })).toBe('From the chat I can only change when Morning new-ticket check runs.')
  })

  it('answers a change to the Software watchlist’s software with what the chat can do to it', () => {
    expect(crossWords(crossed('change the React version', 'only_schedule'), { workflow: 'Software watchlist', editsWatchlist: true })).toBe(
      'From the chat I can add software to the Software watchlist, remove it, or change when the watchlist runs.',
    )
  })

  it('says a day left out of a schedule plainly, never “run things except Friday”', () => {
    expect(crossWords(crossed('except Friday', 'how_often'))).toBe('I can’t leave days out of a schedule yet.')
    expect(crossWords(crossed('excluding Fridays', 'how_often'))).toBe('I can’t leave days out of a schedule yet.')
    expect(crossWords(crossed('twice a week', 'how_often'))).toBe('I can’t run things twice a week yet.')
  })

  it('leaves an edit’s parts to the edit card, which marks every one of them itself', () => {
    expect(leftoverParts(editCant as PlannerReply)).toEqual([])
    expect(leftoverParts(editUnclear as PlannerReply)).toEqual([])
  })
})

describe('the mark of one of the card’s three parts, from the marks of what it holds', () => {
  it('shows the question asked now first, then a part it can’t do, then a question for later, and a tick only when all is done', () => {
    expect(partMark(['ok', 'later', 'ask'])).toBe('ask')
    expect(partMark(['ok', 'later', 'no'])).toBe('no')
    expect(partMark(['ok', 'later'])).toBe('later')
    expect(partMark(['ok', 'ok'])).toBe('ok')
    expect(partMark([]), 'a part with nothing in it is left off the card, so its mark is never read').toBe('ok')
  })
})

describe('the next step of a cross', () => {
  it('asks a clause it didn’t follow, or one that is a question of its own, as its own message', () => {
    expect(askOfCross(crossed('flibber the wotsit', 'not_followed'))).toBe('flibber the wotsit')
    expect(askOfCross(crossed('how many tickets are open?', 'ask_on_its_own'))).toBe('how many tickets are open?')
  })

  it('treats a cross with no reason as one it didn’t follow, as its words do', () => {
    expect(askOfCross(crossed('flibber', null))).toBe('flibber')
  })

  it('leaves a watch request’s own time to the Software watchlist’s offer', () => {
    expect(askOfCross(crossed('every weekday at 9', 'own_time'))).toBeNull()
  })

  it('leaves a cross that already sits on a card with its own button alone', () => {
    expect(askOfCross(crossed('send email', 'cant_do'))).toBeNull()
    expect(askOfCross(crossed('skip the yes', 'skip_approval'))).toBeNull()
  })
})

describe('a free reply and the fallback card draw no crosses', () => {
  const part = crossed('flibber', 'not_followed')
  it('answers the whole message, so none is left over', () => {
    expect(leftoverParts({ trace_id: null, answer: 'reply', form: 'answer', text: 'Hi.', choices: [], offer: null, looked_at: [], about: [], parts: [part] })).toEqual([])
    expect(leftoverParts({ trace_id: null, answer: 'didnt_follow', parts: [part] })).toEqual([])
  })
})

describe('a refusal’s rest', () => {
  const skip: PartView = { text: 'Skip the approval', mark: 'cant', reason: 'skip_approval', note: null, choices: [] }
  const close: PartView = { text: 'close the old tickets', mark: 'cant', reason: 'cant_do', note: 'I can’t close the old tickets.', choices: [] }
  const refused = (rest: string, parts: PartView[]): PlannerReply => ({ trace_id: null, answer: 'refused', reason: 'skip_approval', said: 'Skip the approval', rest, parts })

  it('says why it can’t do the rest when it offers no set-up, and leaves the skip to the card', () => {
    expect(leftoverParts(refused('', [skip, close]))).toEqual([close])
  })

  it('draws nothing beside a rest it offers to set up with a yes', () => {
    const withAYes: PartView = { text: 'create a ticket', mark: 'cant', reason: 'with_a_yes', note: null, choices: [] }
    expect(leftoverParts(refused('create a ticket', [skip, withAYes]))).toEqual([])
  })
})
