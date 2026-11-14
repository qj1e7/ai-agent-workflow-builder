import { describe, expect, it } from 'vitest'
import editCant from '../../../../contracts/fixtures/planner/answer.edit.cant.json'
import editUnclear from '../../../../contracts/fixtures/planner/answer.edit.unclear.json'
import type { PartView, PlannerReply } from '../../api/types'
import { crossWords, leftoverParts, partMark } from './parts'

const crossed = (text: string, reason: PartView['reason']): PartView => ({ text, mark: 'cant', reason, note: null, choices: [] })

describe('the edit answer’s parts', () => {
  it('words a change other than when it runs, and a schedule it can’t hold, in the spec’s words', () => {
    expect(crossWords(crossed('Pause the morning check', 'only_schedule'))).toBe('From the chat I can only change when it runs.')
    expect(crossWords(crossed('monthly', 'how_often'))).toBe('I can’t run things monthly yet.')
  })

  it('names the workflow in a change it can’t make, once the card knows which', () => {
    expect(crossWords(crossed('Pause the morning check', 'only_schedule'), { workflow: 'Morning new-ticket check' })).toBe('From the chat I can only change when Morning new-ticket check runs.')
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
