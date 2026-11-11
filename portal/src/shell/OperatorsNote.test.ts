import { describe, expect, it } from 'vitest'
import { operatorsNoteWords } from './OperatorsNote'

const person = (display: string, operator = true) => ({ display, operator })

describe('the note on a page someone who is not an Operator reads', () => {
  it('names every Operator on the People list, as people say a list', () => {
    expect(operatorsNoteWords('workflows', [person('Alice'), person('Bob', false), person('Carol')])).toBe('Only Operators change workflows. Ask Alice or Carol.')
    expect(operatorsNoteWords('workflows', [person('Alice'), person('Carol'), person('Dave')])).toBe('Only Operators change workflows. Ask Alice, Carol or Dave.')
    expect(operatorsNoteWords('the watchlist', [person('Carol')])).toBe('Only Operators change the watchlist. Ask Carol.')
  })

  it('names nobody while the People list loads', () => {
    expect(operatorsNoteWords('this workflow', undefined)).toBe('Only Operators change this workflow.')
  })
})
