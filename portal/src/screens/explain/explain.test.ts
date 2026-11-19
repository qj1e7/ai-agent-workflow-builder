import { describe, expect, it } from 'vitest'
import current from '../../../../contracts/fixtures/builder/explain.json'
import older from '../../../../contracts/fixtures/builder/explain.older.json'
import explainOne from '../../../../contracts/fixtures/planner/answer.explain.json'
import explainSeveral from '../../../../contracts/fixtures/planner/answer.explain.choices.json'
import explainIt from '../../../../contracts/fixtures/planner/answer.explain.it.json'
import type { ExplainReply, PlannerReply, WorkflowExplained } from '../../api/types'
import missingOne from '../../../../contracts/fixtures/planner/answer.explain.missing.json'
import { ApiError } from '../../api/client'
import { approvesGist, approvalGist, explainAnswerOf, explainAsk, explainStateOf, explainPath, explainTitle, flagsGist, segmentsOfText, settingsGist, stepsGist, touchesGist, workflowInFocus } from './explain'

const REPORT = current as WorkflowExplained
const OLDER = older as WorkflowExplained
const ONE = explainOne as ExplainReply
const SEVERAL = explainSeveral as ExplainReply
const IT = explainIt as ExplainReply

describe('the gist of each section', () => {
  it('counts the blocks', () => {
    expect(stepsGist(REPORT.steps)).toBe('8 blocks')
    expect(stepsGist(REPORT.steps.slice(0, 1))).toBe('1 block')
  })

  it('names the systems it reads, writes and posts to, each once, in that order', () => {
    expect(touchesGist(REPORT.touches)).toBe('Reads GitHub and Jira · Writes Jira')
    const posts = [{ ...REPORT.touches[3]!, action: 'posts' as const, system: 'Slack' }]
    expect(touchesGist([...REPORT.touches, ...posts])).toBe('Reads GitHub and Jira · Writes Jira · Posts Slack')
  })

  it('says it changes nothing when nothing is read, written or posted', () => {
    expect(touchesGist([])).toBe('Changes nothing')
  })

  it('falls back to the place when code cannot tell the system, and to the bare verb when it has neither', () => {
    const base = REPORT.touches[0]!
    expect(touchesGist([{ ...base, system: null, place: 'fastapi/fastapi' }])).toBe('Reads fastapi/fastapi')
    expect(touchesGist([{ ...base, system: null, place: null }])).toBe('Reads')
  })

  it('counts what was fixed and what passed, and what still needs someone', () => {
    expect(flagsGist(REPORT)).toBe(`${REPORT.fixed.length} fixed for you · ${REPORT.passed.length} passed`)
    expect(flagsGist(OLDER)).toBe(`1 to fix · ${OLDER.fixed.length} fixed for you · ${OLDER.passed.length} passed`)
    const asked: WorkflowExplained = { ...REPORT, fixed: [], passed: [], flags: [{ ...OLDER.flags[0]!, clears: 'needs_an_answer' }, { ...OLDER.flags[0]!, clears: 'approver_may_accept' }] }
    expect(flagsGist(asked)).toBe('1 for an Approver · 1 answer needed')
    expect(flagsGist({ ...REPORT, fixed: [], passed: [] })).toBe('No flags')
  })

  it('counts the writes that wait for a yes, and the ones that cannot run', () => {
    expect(approvesGist(REPORT.approves)).toBe('1 waits for a yes on each run')
    const write = REPORT.approves[0]!
    expect(approvesGist([write, write])).toBe('2 wait for a yes on each run')
    expect(approvesGist([{ ...write, decides: 'set_up', approvers: null }])).toBe('1 on the set-up approval')
    expect(approvesGist([{ ...write, decides: 'refused', approvers: null }])).toBe('1 refused')
    expect(approvesGist([{ ...write, decides: 'cant_run_yet', approvers: null }])).toBe('1 can’t run yet')
    expect(approvesGist([])).toBe('Writes nothing')
  })

  it('counts the settings, and says what is still needed or guessed', () => {
    expect(settingsGist(REPORT.settings)).toBe(`${REPORT.settings.length} settings`)
    const needed = { ...REPORT.settings[0]!, mark: 'needed' as const, value: null }
    const guessed = { ...REPORT.settings[0]!, mark: 'guessed' as const }
    expect(settingsGist([needed, guessed, needed])).toBe('2 needed · 1 guessed')
  })

  it('leads the approval row with the first sentence of its words', () => {
    expect(approvalGist(REPORT.approval)).toBe('None needed')
    expect(approvalGist('One Approver says yes')).toBe('One Approver says yes')
  })
})

describe('where Explain goes', () => {
  it('has a page for the workflow, and for one version of it', () => {
    expect(explainPath('uc_1', null)).toBe('/workflows/uc_1/explain')
    expect(explainPath('uc_1', 3)).toBe('/workflows/uc_1/explain?version=3')
    expect(explainPath('uc a', null)).toBe('/workflows/uc%20a/explain')
  })

  it('titles the panel Explain, or Explain, version N', () => {
    expect(explainTitle(null)).toBe('Explain')
    expect(explainTitle(2)).toBe('Explain, version 2')
  })
})

const reply = (answer: PlannerReply['answer'], extra: object = {}): PlannerReply => ({ parts: [], trace_id: null, answer, ...extra }) as PlannerReply

describe('the workflow in focus', () => {
  const edit = reply('edit', { use_case_id: 'uc_edit' })
  const stopped = reply('why_stopped', { use_case_id: 'uc_stopped' })

  it('is the workflow open in the side panel', () => {
    expect(workflowInFocus({ kind: 'workflow', id: 'uc_panel' }, [edit])).toBe('uc_panel')
  })

  it('is the workflow an Explain item in the side panel is about, whatever its version', () => {
    expect(workflowInFocus({ kind: 'explain', id: 'uc_panel', version: 2 }, [edit])).toBe('uc_panel')
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

describe('the reworded In short', () => {
  it('splits its curly-quoted values from the words around them, so they are drawn as code’s are', () => {
    expect(segmentsOfText('It reads GitHub “fastapi/fastapi” and Jira “MOCK”.')).toEqual([
      { text: 'It reads GitHub ', quoted: false },
      { text: 'fastapi/fastapi', quoted: true },
      { text: ' and Jira ', quoted: false },
      { text: 'MOCK', quoted: true },
      { text: '.', quoted: false },
    ])
  })

  it('is one plain segment when nothing is quoted', () => {
    expect(segmentsOfText('Nothing changes.')).toEqual([{ text: 'Nothing changes.', quoted: false }])
  })
})

describe('what the report shows while it loads, and when it cannot', () => {
  it('is loading until the report or an error comes', () => {
    expect(explainStateOf({ data: undefined, error: null })).toEqual({ kind: 'loading' })
  })

  it('is the report once it came', () => {
    expect(explainStateOf({ data: REPORT, error: null })).toEqual({ kind: 'report', report: REPORT })
  })

  it('says the server’s own words for a workflow that is gone or has nothing to explain', () => {
    const words = 'Nothing to explain: this version ran on the shared n8n workflow, so the platform kept no copy of its blocks.'
    expect(explainStateOf({ data: undefined, error: new ApiError(409, { detail: words }) })).toEqual({ kind: 'said', words })
    expect(explainStateOf({ data: undefined, error: new ApiError(404, { detail: 'That workflow isn’t here.' }) })).toEqual({ kind: 'said', words: 'That workflow isn’t here.' })
  })

  it('is a failed load, with a reason to try again, for anything else', () => {
    expect(explainStateOf({ data: undefined, error: new ApiError(500, {}) })).toEqual({ kind: 'failed' })
    expect(explainStateOf({ data: undefined, error: new TypeError('network') })).toEqual({ kind: 'failed' })
  })
})

describe('a choice on Which workflow?', () => {
  it('asks the Planner to explain the one she picked, by its name', () => {
    expect(explainAsk('FastAPI release check')).toBe('Explain the FastAPI release check')
  })
})
