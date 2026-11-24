import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import bobSetUp from '../../../../contracts/fixtures/builder/setup-approval.bob.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { SetUpApprovalView } from '../../api/types'
import { SetUpApproval } from './SetUpApprovalPage'

const BASE = bobSetUp as SetUpApprovalView

type Evidence = NonNullable<SetUpApprovalView['fix']>
const EVIDENCE: Evidence = {
  fix_id: 'fix_01FIRST',
  run_id: 'run_01JB9',
  use_case_id: 'uc_01JB9',
  asked_by: 'Alice',
  answered_by: null,
  made_by: 'fix_drafter',
  cause: 'GitHub answered, but the “Read release” block couldn’t find the field “tag”.',
  failed_part: ['Read release'],
  changes: [{ block: 'Read release', parameter: 'field', before: 'tag', after: 'tag_name' }],
  scenarios: [
    { name: 'replay_the_stop', kind: 'replay_the_stop', verdict: 'passed', step: null, why: null },
    { name: 'A newer release', kind: 'newer', verdict: 'passed', step: null, why: null },
    { name: 'No newer release', kind: 'none_newer', verdict: 'failed', step: 'Compare', why: 'It stopped at the Compare block.' },
    { name: 'Late answer', kind: null, verdict: 'not_tried', step: null, why: null },
  ],
  checks: [
    { check: 'inside_the_failed_part', passed: true, words: 'The change stays inside the blocks where the run stopped.' },
    { check: 'every_scenario_passed', passed: false, words: 'Every scenario passed on practice systems.' },
  ],
  read_list: 'fastapi/fastapi',
}

const view = (over: Partial<SetUpApprovalView> = {}): SetUpApprovalView => ({ ...BASE, fix: EVIDENCE, ...over })

function draw(v: SetUpApprovalView): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <SetUpApproval view={v} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))

describe('the approval page for a fix', () => {
  it('says whose request it is, not whose draft', () => {
    const words = text(draw(view()))
    expect(words).toContain('Set-up approval, from Alice’s request for a fix')
    expect(words).not.toContain('’s draft')
  })

  it('shows the cause, and the change from what it was to what it becomes', () => {
    const words = text(draw(view()))
    expect(words).toContain('The cause GitHub answered, but the “Read release” block couldn’t find the field “tag”.')
    expect(words).toMatch(/Read release\s+Field it reads\s+tag\s+→\s+tag_name/)
  })

  it('shows each scenario with the platform’s verdict, and why one failed', () => {
    const words = text(draw(view()))
    expect(words).toContain('A newer release Passed')
    expect(words).toContain('No newer release Failed')
    expect(words).toContain('It stopped at the Compare block.')
    expect(words).toContain('Late answer Not tried')
  })

  it('shows each of the platform’s checks in its words, passed or not', () => {
    const words = text(draw(view()))
    expect(words).toContain('Passed The change stays inside the blocks where the run stopped.')
    expect(words).toContain('Did not pass Every scenario passed on practice systems.')
  })

  it('says which repository joins the read list, and nothing when none does', () => {
    expect(text(draw(view()))).toContain('fastapi/fastapi')
    expect(text(draw(view({ fix: { ...EVIDENCE, read_list: null } })))).not.toContain('read list')
  })

  it('names a block’s parameter in plain words, not by its path', () => {
    const changes = [
      { block: 'Read release', parameter: 'place', before: 'a/b', after: 'c/d' },
      { block: 'Make ticket', parameter: 'title', before: 'Old', after: 'New' },
      { block: 'Tell', parameter: 'assignments.assignments[].value', before: 'x', after: 'y' },
    ]
    const words = text(draw(view({ fix: { ...EVIDENCE, changes } })))
    expect(words).toContain('Read release Place it reads a/b')
    expect(words).toContain('Make ticket Title Old')
    expect(words).toContain('Tell Value x')
  })

  it('says who made the change when a person did', () => {
    expect(text(draw(view({ fix: { ...EVIDENCE, made_by: 'person', answered_by: 'Carol' } })))).toContain('Carol answered the question, and the platform made the change from the answer.')
  })

  it('says the checks are the platform’s, never the AI’s summary', () => {
    expect(text(draw(view()))).toContain('These come from the platform’s own checks, never from an AI’s summary.')
  })

  it('shows Approve and Decline only to someone who may decide, and says why not to a party', () => {
    expect(buttons(draw(view({ you_can_decide: true, why_not: null })))).toContain('Approve')
    const party = draw(view({ you_can_decide: false, why_not: 'You can’t approve your own work.' }))
    expect(buttons(party)).not.toContain('Approve')
    expect(text(party)).toContain('You can’t approve your own work.')
  })

  it('leaves a drafted workflow’s approval as it was', () => {
    const words = text(draw({ ...BASE, fix: null }))
    expect(words).toContain('’s draft')
    expect(words).not.toContain('The cause')
  })
})
