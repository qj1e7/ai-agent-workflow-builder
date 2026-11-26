import { describe, expect, it } from 'vitest'
import explainOne from '../../../../contracts/fixtures/planner/answer.explain.json'
import explainSeveral from '../../../../contracts/fixtures/planner/answer.explain.choices.json'
import explainIt from '../../../../contracts/fixtures/planner/answer.explain.it.json'
import missingOne from '../../../../contracts/fixtures/planner/answer.explain.missing.json'
import type { ExplainReply, PlannerReply } from '../../api/types'
import { explainAnswerOf, explainAsk, workflowInFocus } from './explain'

const ONE = explainOne as ExplainReply
const SEVERAL = explainSeveral as ExplainReply
const IT = explainIt as ExplainReply

const reply = (answer: PlannerReply['answer'], extra: object = {}): PlannerReply => ({ parts: [], trace_id: null, answer, ...extra }) as PlannerReply

describe('the workflow in focus', () => {
  const edit = reply('edit', { use_case_id: 'uc_edit' })
  const stopped = reply('why_stopped', { use_case_id: 'uc_stopped' })

  it('is the workflow open in the side panel', () => {
    expect(workflowInFocus({ kind: 'workflow', id: 'uc_panel' }, [edit])).toBe('uc_panel')
  })

  it('is the newest answer that names exactly one workflow when the panel shows none', () => {
    expect(workflowInFocus(null, [edit, stopped])).toBe('uc_stopped')
    expect(workflowInFocus({ kind: 'needs' }, [stopped, edit])).toBe('uc_edit')
    expect(workflowInFocus({ kind: 'run', id: 'run_1' }, [stopped])).toBe('uc_stopped')
  })

  it('skips an answer that names several or none, and keeps looking back', () => {
    expect(workflowInFocus(null, [stopped, SEVERAL, reply('ideas'), reply('edit', { use_case_id: null })])).toBe('uc_stopped')
  })

  it('counts an Explain answer that named one workflow', () => {
    expect(workflowInFocus(null, [edit, ONE])).toBe('uc_01JFASTAPI')
  })

  it('is nothing when nothing names one', () => {
    expect(workflowInFocus(null, [])).toBeNull()
    expect(workflowInFocus(null, [SEVERAL, reply('ideas')])).toBeNull()
  })
})

describe('what an Explain answer asks of the page', () => {
  const MISSING = missingOne as ExplainReply

  it('explains the one workflow it named, whatever is in focus', () => {
    expect(explainAnswerOf(ONE, 'uc_other')).toEqual({ kind: 'one', id: 'uc_01JFASTAPI', name: 'FastAPI release check' })
  })

  it('explains the one in focus for “explain it”, by the name its choices carry', () => {
    expect(explainAnswerOf(IT, 'uc_01JB8')).toEqual({ kind: 'one', id: 'uc_01JB8', name: 'React release check' })
  })

  it('asks which when “explain it” has nothing in focus', () => {
    expect(explainAnswerOf(IT, null)).toEqual({ kind: 'which' })
  })

  it('asks which when several workflows matched words, even with one in focus', () => {
    expect(explainAnswerOf(SEVERAL, 'uc_01JB8')).toEqual({ kind: 'which' })
  })

  it('asks which when the workflow in focus is not one of the choices', () => {
    expect(explainAnswerOf(IT, 'uc_gone')).toEqual({ kind: 'which' })
  })

  it('says it found none when the words matched nothing', () => {
    expect(explainAnswerOf(MISSING, 'uc_01JB8')).toEqual({ kind: 'missing' })
  })
})

describe('a choice on Which workflow?', () => {
  it('asks the Planner to explain the one they picked, by its name', () => {
    expect(explainAsk('FastAPI release check')).toBe('Explain the FastAPI release check')
  })
})
