import troubleshooting from '@contracts/fixtures/troubleshooting/failure.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { TroubleshootingOut } from '../../api/types'
import { OPERATORS_RETRY, Troubleshooting } from './Outcome'
import type { Phase } from './runModel'

vi.mock('../home/HomeItem', () => ({ RetryButton: ({ label }: { label: string }) => <button type="button">{label}</button> }))
vi.mock('./Report', () => ({ ReportToSupport: () => <div data-report="form">Report to support form</div> }))

const ADVICE = troubleshooting as TroubleshootingOut
const nameOf = (id: string) => id

type Failed = Extract<Phase, { state: 'failed' }>
const failed = (over: Partial<Failed> = {}): Failed => ({
  state: 'failed',
  stage: 'working',
  reason: 'AgentError',
  retryable: true,
  message: 'UpstreamUnavailable: GitHub returned 503 three times. Then start a new run.',
  ...over,
})

const OPERATOR = { id: 'alice', name: 'Alice', operator: true }
const APPROVER = { id: 'bob', name: 'Bob', operator: false }

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

function draw(failure: Failed, advice: TroubleshootingOut | undefined, me = OPERATOR, loading = false): string {
  return renderToStaticMarkup(<Troubleshooting runId="run_1" failure={failure} advice={advice} loading={loading} me={me} reports={[]} nameOf={nameOf} />)
}

const withAnswers = (over: Partial<TroubleshootingOut['answers']>, retry: TroubleshootingOut['answers']['retry']): TroubleshootingOut => ({
  ...ADVICE,
  answers: { ...ADVICE.answers, ...over, retry, next: retry.possible ? 'retry' : 'report' },
})

describe('the four answers', () => {
  it('names them in order and ends with what to do', () => {
    const html = text(draw(failed(), ADVICE))
    const at = ['What happened', 'What was affected', 'Can it be fixed safely', 'What should you do'].map((name) => html.indexOf(name))
    expect(at.every((index) => index >= 0)).toBe(true)
    expect(at).toEqual([...at].sort((a, b) => a - b))
    expect(html).toContain(ADVICE.answers.what_affected)
    expect(html).toContain(ADVICE.answers.can_fix)
  })

  it('shows the failure text in plain words, without the error type, and every sentence the platform wrote', () => {
    const html = text(draw(failed({ message: 'UpstreamUnavailable: GitHub returned 503 three times. Start a new run.' }), ADVICE))
    expect(html).toContain('The failure text: GitHub returned 503 three times. Start a new run.')
    expect(html).not.toContain('UpstreamUnavailable')
  })
})

describe('what to do', () => {
  it('offers Retry the run to an Operator when the platform says the run can run again', () => {
    const html = draw(failed(), withAnswers({}, { possible: true, asks_again: true }))
    expect(html).toContain('Retry the run')
    expect(html).not.toContain('data-report')
  })

  it('says an Operator can retry, instead of showing a button an Approver cannot use', () => {
    const html = draw(failed(), withAnswers({}, { possible: true, asks_again: true }), APPROVER)
    expect(html).not.toContain('<button')
    expect(text(html)).toContain(OPERATORS_RETRY)
  })

  it('offers Report to support, and no Retry, when the stop can’t be retried', () => {
    const html = draw(failed({ retryable: false }), withAnswers({}, { possible: false, asks_again: false }))
    expect(html).toContain('data-report')
    expect(html).not.toContain('<button')
  })

  it('decides the same way when the troubleshooter has not answered yet', () => {
    expect(draw(failed({ retryable: true }), undefined, OPERATOR, true)).toContain('Retry the run')
    expect(draw(failed({ retryable: false }), undefined, OPERATOR, true)).toContain('data-report')
    expect(text(draw(failed(), undefined, OPERATOR, true))).toContain('The AI troubleshooter is looking at what happened.')
  })

  it('shows the troubleshooter’s advice whole, including a new run before the write step', () => {
    const advice: TroubleshootingOut = {
      ...ADVICE,
      advice: { ...ADVICE.advice, suggestion: 'Ask a maintainer to fix it, then start a new run. Check Jira first.' },
    }
    const html = text(draw(failed({ stage: 'working', retryable: false }), advice))
    expect(html).toContain('Ask a maintainer to fix it, then start a new run. Check Jira first.')
  })
})
