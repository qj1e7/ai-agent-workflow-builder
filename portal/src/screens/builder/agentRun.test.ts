import { describe, expect, it } from 'vitest'
import list from '@contracts/fixtures/cards/list.json'
import plan from '@contracts/fixtures/cards/plan.use-one.json'
import type { CardView, PlannedAgent } from '../../api/types'
import { ApiError } from '../../api/client'
import { checkRun, defaultName, exampleValues, firstRunProblem, normalized, refusedRun, startValues, type RunAgent } from './agentRun'

const starter = list.cards[0] as CardView
const planned = plan.agents[0] as PlannedAgent

function agent(values: Record<string, string>): RunAgent {
  return { card: starter, values, missing: [] }
}

describe('starting values', () => {
  it('uses what the Room lead found and leaves the rest empty', () => {
    expect(startValues({ card: planned.card, values: planned.values, missing: planned.missing })).toEqual({
      'GitHub repository': 'langchain-ai/langgraph',
      'Jira project': '',
    })
  })

  it('offers the examples for an agent from the library', () => {
    expect(exampleValues(starter)).toEqual({ 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' })
  })

  it('names the use case after its agents', () => {
    expect(defaultName([agent({})])).toBe('Release checker')
    expect(defaultName([agent({}), agent({})])).toBe('Release checker and Release checker')
  })
})

describe('checking the form before it is sent', () => {
  it('sends the name, the task and each agent with its values', () => {
    const checked = checkRun(' Check LangGraph ', ' Check it. ', [agent({ 'GitHub repository': 'https://github.com/langchain-ai/langgraph', 'Jira project': 'mock' })])
    expect(checked).toEqual({
      ok: true,
      body: {
        name: 'Check LangGraph',
        instruction: 'Check it.',
        agents: [{ card_id: 'crd_release_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }],
      },
    })
  })

  it('uses the name when there is no task', () => {
    const checked = checkRun('Mine', '  ', [agent(exampleValues(starter))])
    expect(checked.ok && checked.body.instruction).toBe('Mine')
  })

  it('names each empty or wrong field and the empty name', () => {
    const checked = checkRun(' ', 'x', [agent({ 'GitHub repository': 'nope', 'Jira project': '' })])
    expect(checked.ok).toBe(false)
    if (checked.ok) return
    expect(checked.problems.name).toBe('Give the use case a name.')
    expect(checked.problems.values['0:GitHub repository']).toBe('Write it as owner/name, such as langchain-ai/langgraph.')
    expect(checked.problems.values['0:Jira project']).toBe('Fill this in.')
    expect(firstRunProblem(checked.problems, [agent({})])).toBe('name')
  })

  it('finds the first field with a problem when the name is fine', () => {
    const checked = checkRun('Mine', 'x', [agent({ 'GitHub repository': 'a/b', 'Jira project': '' })])
    expect(!checked.ok && firstRunProblem(checked.problems, [agent({})])).toBe('0:Jira project')
  })

  it('writes a Jira key in capitals and takes a text value as one line', () => {
    expect(normalized('jira_project', ' mock ')).toBe('MOCK')
    expect(normalized('text', ' hi ')).toBe('hi')
  })
})

describe('what the platform refuses', () => {
  const refusal = (detail: unknown) => new ApiError(422, { detail })

  it('maps a value to the field it names', () => {
    const refused = refusedRun(refusal([{ loc: ['body', 'agents', 0, 'values', 'Jira project'], msg: 'bad' }]), [agent({})])
    expect(refused?.values).toEqual({ '0:Jira project': 'Write the project key, such as MOCK.' })
  })

  it('says an agent that is gone on the form', () => {
    expect(refusedRun(refusal([{ loc: ['body', 'agents', 0, 'card_id'], msg: 'unknown' }]), [agent({})])?.form).toBe('This agent is no longer available.')
  })

  it('leaves other errors to the page', () => {
    expect(refusedRun(new ApiError(409, { detail: 'x' }), [agent({})])).toBeNull()
    expect(refusedRun(new Error('x'), [])).toBeNull()
  })
})
