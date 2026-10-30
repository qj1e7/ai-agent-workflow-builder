import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { refusedWords } from './newQueries'

describe('the words of a workflow the platform refused', () => {
  it('names the agent’s input a problem is about', () => {
    const refused = new ApiError(422, {
      detail: [
        { loc: ['body', 'agents', 0, 'values', 'Jira project'], msg: 'Required. Write the project key, such as MOCK.' },
        { loc: ['body', 'agents', 1, 'card_id'], msg: 'No such agent.' },
      ],
    })
    expect(refusedWords(refused)).toEqual(['Jira project: Required. Write the project key, such as MOCK.', 'No such agent.'])
  })

  it('keeps a new agent’s problems as they are, and has no words for an error that is not a refusal', () => {
    expect(refusedWords(new ApiError(422, { problems: [{ field: 'blocks.2.tool', message: 'Pick a tool for this block.' }] }))).toEqual(['Pick a tool for this block.'])
    expect(refusedWords(new ApiError(500, null))).toEqual([])
  })
})
