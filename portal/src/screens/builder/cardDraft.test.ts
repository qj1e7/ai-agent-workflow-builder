import { describe, expect, it } from 'vitest'
import list from '@contracts/fixtures/cards/list.json'
import tools from '@contracts/fixtures/cards/tools.json'
import check from '@contracts/fixtures/cards/check.json'
import type { ToolView } from '../../api/types'
import { approvalWords, copyOf, draftOf, firstProblemKey, removeAt, replaceAt, sortProblems, toDefinition } from './cardDraft'

const starter = list.cards[0]!
const toolList = tools.tools as ToolView[]

describe('a card as it is edited', () => {
  it('turns a saved card into a draft and back without losing anything', () => {
    const definition = toDefinition(draftOf(starter))
    expect(definition.name).toBe('Release checker')
    expect(definition.blocks.map((block) => block.tool)).toEqual(['github.read_releases', 'jira.search', 'jira.create_ticket'])
    expect(definition.inputs[1]).toMatchObject({ name: 'Jira project', kind: 'jira_project', example: 'MOCK' })
    expect(definition.good_for).toEqual(starter.good_for)
    expect(definition.approvals).toEqual([{ tool: 'jira.create_ticket', approvers: 1 }])
  })

  it('names a copy so it is not mistaken for the starter', () => {
    expect(copyOf(starter).name).toBe('Release checker copy')
  })

  it('sends no tool for a step with no tool, and trims what was typed', () => {
    const draft = { ...draftOf(starter), name: '  Mine ', blocks: [{ say: ' Say it. ', tool: '' }] }
    expect(toDefinition(draft).blocks).toEqual([{ say: 'Say it.', tool: null }])
    expect(toDefinition(draft).name).toBe('Mine')
  })

  it('changes and removes one item and leaves the list it was given alone', () => {
    const blocks = draftOf(starter).blocks
    expect(replaceAt(blocks, 1, { say: 'x' }).map((block) => block.say)[1]).toBe('x')
    expect(removeAt(blocks, 0)).toHaveLength(2)
    expect(blocks).toHaveLength(3)
  })
})

describe('the platform check', () => {
  const sorted = sortProblems(check.problems)

  it('puts a problem next to its field and keeps the rest together', () => {
    expect(Object.keys(sorted.byField)).toEqual(['name'])
    expect(sorted.general).toHaveLength(1)
  })

  it('keys step and input problems by their row', () => {
    const rows = sortProblems([
      { field: 'blocks.2.tool', message: 'a' },
      { field: 'inputs.0.name', message: 'b' },
      { field: 'inputs.0', message: 'c' },
    ])
    expect(rows.byField['blocks.2']).toEqual(['a'])
    expect(rows.byField['inputs.0']).toEqual(['b', 'c'])
  })

  it('finds the first field in page order', () => {
    const rows = sortProblems([
      { field: 'blocks.1.say', message: 'a' },
      { field: 'inputs.0.kind', message: 'b' },
    ])
    expect(firstProblemKey(rows, 2, 1)).toBe('inputs.0')
    expect(firstProblemKey(sortProblems([]), 2, 1)).toBeNull()
  })

  it('says each approval with the tool in plain words', () => {
    expect(approvalWords([{ tool: 'jira.create_ticket', approvers: 2 }], toolList)).toEqual([
      'Create a Jira ticket: 2 Approvers must approve it first.',
    ])
    expect(approvalWords([], toolList)).toEqual([])
  })
})
