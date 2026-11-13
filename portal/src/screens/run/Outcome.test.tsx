import troubleshooting from '@contracts/fixtures/troubleshooting/failure.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { TroubleshootingOut } from '../../api/types'
import { NOT_YET_NO_MODEL, OPERATORS_REPORT, OPERATORS_RETRY, Troubleshooting } from './Outcome'
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

describe('the three answers', () => {
  it('names them in order, answers Safe to retry, and has no fourth answer', () => {
    const html = text(draw(failed(), ADVICE))
    const at = ['What happened', 'Affected', 'Safe to retry'].map((name) => html.indexOf(name))
    expect(at.every((index) => index >= 0)).toBe(true)
    expect(at).toEqual([...at].sort((a, b) => a - b))
    expect(html).toContain(ADVICE.answers.what_affected)
    expect(html).toContain(ADVICE.answers.safe_to_retry)
    expect(html).not.toContain('What should you do')
    expect(html).not.toContain('Can it be fixed safely')
    expect((draw(failed(), ADVICE).match(/<dt/g) ?? []).length).toBe(3)
  })

  it('puts the next step under the answers', () => {
    const html = text(draw(failed(), ADVICE))
    expect(html.indexOf('Retry')).toBeGreaterThan(html.indexOf(ADVICE.answers.safe_to_retry))
  })

  it('keeps the failure text behind Details, in plain words without the error type, and every sentence the platform wrote', () => {
    const html = draw(failed({ message: 'UpstreamUnavailable: GitHub returned 503 three times. Start a new run.' }), ADVICE)
    const details = /<details[^>]*>([\s\S]*?)<\/details>/.exec(html)?.[1] ?? ''
    expect(text(details)).toContain('Details')
    expect(text(details)).toContain('GitHub returned 503 three times. Start a new run.')
    expect(html.replace(details, '')).not.toContain('GitHub returned 503')
    expect(html).not.toContain('UpstreamUnavailable')
  })

  it('answers What happened in the one sentence the troubleshooter wrote, and keeps the likely cause for Details', () => {
    const html = draw(failed(), ADVICE)
    const details = /<details[^>]*>([\s\S]*?)<\/details>/.exec(html)?.[1] ?? ''
    const answer = /<dt>What happened<\/dt><dd[^>]*>([\s\S]*?)<\/dd>/.exec(html)?.[1] ?? ''
    expect(text(answer)).toBe(ADVICE.answers.what_happened)
    expect(text(details)).toContain(ADVICE.advice.likely_cause)
  })
})

describe('the next step', () => {
  it('offers Retry the run to an Operator when the platform says the run can run again', () => {
    const html = draw(failed(), withAnswers({}, { possible: true, asks_again: true }))
    expect(html).toContain('>Retry<')
    expect(html).not.toContain('data-report')
  })

  it('says an Operator can retry, instead of showing a button an Approver cannot use', () => {
    const html = draw(failed(), withAnswers({}, { possible: true, asks_again: true }), APPROVER)
    expect(html).not.toContain('<button')
    expect(text(html)).toContain(OPERATORS_RETRY)
    expect(text(html)).toContain(ADVICE.answers.safe_to_retry)
  })

  it('shows an Approver the answers and a note, with no Report to support form, when the stop can’t be retried', () => {
    const html = draw(failed({ retryable: false }), withAnswers({ safe_to_retry: 'No. This kind of stop can’t be retried.' }, { possible: false, asks_again: false }), APPROVER)
    expect(html).not.toContain('data-report')
    expect(html).not.toContain('<button')
    expect(text(html)).toContain(OPERATORS_REPORT)
    expect(text(html)).toContain('No. This kind of stop can’t be retried.')
  })

  it('says Not yet, and holds Retry back, while no AI model is connected', () => {
    const html = renderToStaticMarkup(
      <Troubleshooting runId="run_1" failure={failed()} advice={ADVICE} loading={false} me={OPERATOR} reports={[]} nameOf={nameOf} modelOff />,
    )
    expect(text(html)).toContain(NOT_YET_NO_MODEL)
    expect(text(html)).not.toContain(ADVICE.answers.safe_to_retry)
    expect(html).not.toContain('<button')
  })

  it('offers Report to support, and no Retry, when the stop can’t be retried', () => {
    const html = draw(failed({ retryable: false }), withAnswers({}, { possible: false, asks_again: false }))
    expect(html).toContain('data-report')
    expect(html).not.toContain('<button')
  })

  it('decides the same way when the troubleshooter has not answered yet', () => {
    expect(draw(failed({ retryable: true }), undefined, OPERATOR, true)).toContain('>Retry<')
    expect(draw(failed({ retryable: false }), undefined, OPERATOR, true)).toContain('data-report')
    expect(text(draw(failed(), undefined, OPERATOR, true))).toContain('The AI troubleshooter is looking at what happened.')
  })

  it('shows the platform’s Safe to retry whole, including what to do instead of a retry', () => {
    const said = 'No. This kind of stop can’t be retried. Ask a maintainer to fix it, then start a new run. Check Jira first.'
    const html = text(draw(failed({ stage: 'working', retryable: false }), withAnswers({ safe_to_retry: said }, { possible: false, asks_again: false })))
    expect(html).toContain(said)
  })

  it('says workflow, not template, in Safe to retry', () => {
    const said = 'No. This kind of stop can’t be retried. Ask a maintainer to add the binding to the template, then start a new run.'
    const html = text(draw(failed({ retryable: false }), withAnswers({ safe_to_retry: said }, { possible: false, asks_again: false })))
    expect(html).toContain('add the binding to the workflow, then start a new run.')
    expect(html).not.toContain('template')
  })
})
