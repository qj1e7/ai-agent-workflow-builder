import { describe, expect, it } from 'vitest'
import editCant from '../../../../contracts/fixtures/planner/answer.edit.cant.json'
import editUnclear from '../../../../contracts/fixtures/planner/answer.edit.unclear.json'
import type { PartView, PlannerReply } from '../../api/types'
import { crossWords, leftoverParts } from './parts'

const crossed = (text: string, reason: PartView['reason']): PartView => ({ text, mark: 'cant', reason, note: null, choices: [] })

describe('the edit answer’s parts', () => {
  it('words a change other than when it runs, and a schedule it can’t hold, in the spec’s words', () => {
    expect(crossWords(crossed('Pause the morning check', 'only_schedule'))).toBe('From the chat I can only change when it runs.')
    expect(crossWords(crossed('monthly', 'how_often'))).toBe('I can’t run things monthly yet.')
  })

  it('draws every cross of an edit above the answer, so no part is dropped before the edit card lands', () => {
    expect(leftoverParts(editCant as PlannerReply).map((part) => part.reason)).toEqual(['ask_on_its_own', 'only_schedule'])
    expect(leftoverParts(editUnclear as PlannerReply).map((part) => part.text)).toEqual(['in the afternoon'])
  })
})
