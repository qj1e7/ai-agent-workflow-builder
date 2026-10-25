import { describe, expect, it } from 'vitest'
import cannot from '@contracts/fixtures/cards/plan.cannot-do.json'
import list from '@contracts/fixtures/cards/list.json'
import newAgent from '@contracts/fixtures/cards/plan.new-agent.json'
import useOne from '@contracts/fixtures/cards/plan.use-one.json'
import type { CardView, PlanOut } from '../../api/types'
import { copyOf } from './cardDraft'
import { editorOf, runOfSaved, workOfPlan } from './work'

const starter = list.cards[0] as CardView
const saved = list.cards[1] as CardView

describe('what each plan shows', () => {
  it('shows the agent the Room lead picked with the details it found, and the rest empty', () => {
    const work = workOfPlan(useOne as PlanOut, 'Check LangGraph.')
    expect(work.kind).toBe('run')
    if (work.kind !== 'run') return
    expect(work.intro).toBe('The Room lead picked Release checker.')
    expect(work.agents[0]?.values).toEqual({ 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': '' })
    expect(work.agents[0]?.missing).toEqual(['Jira project'])
    expect(work.instruction).toBe('Check LangGraph.')
    expect(work.questions).toEqual(['Which Jira project should get the ticket?'])
  })

  it('opens the editor on a draft, with the missing tools beside it', () => {
    const work = workOfPlan(newAgent as PlanOut, 'Every Friday summarise.')
    expect(work.kind).toBe('editor')
    if (work.kind !== 'editor') return
    expect(work.cardId).toBeNull()
    expect(work.draft.blocks).toHaveLength(2)
    expect(work.missingTools[0]?.need).toBe('Post in Teams')
  })

  it('says why the Room lead cannot do a task', () => {
    expect(workOfPlan(cannot as PlanOut, 'x')).toMatchObject({ kind: 'cannot', missingTools: [{ need: 'Calendar' }] })
    expect(workOfPlan({ decision: 'model_problem', message: 'The key was refused.' }, 'x')).toEqual({
      kind: 'model',
      message: 'The key was refused.',
    })
  })
})

describe('changing and running saved agents', () => {
  it('never saves over a starter: its copy is a new card', () => {
    const work = editorOf(starter, copyOf(starter))
    expect(work.kind === 'editor' && work.cardId).toBeNull()
  })

  it('saves a change to a team agent as its next version', () => {
    const work = editorOf(saved, copyOf(saved))
    expect(work.kind === 'editor' && work.cardId).toBe(saved.card_id)
  })

  it('offers a saved agent to run, saying it was saved', () => {
    const work = runOfSaved(saved, { 'Jira project': 'MOCK' }, 'Run it.')
    expect(work.kind === 'run' && work.intro).toBe('Saved Weekly summary, version 2.')
  })
})
