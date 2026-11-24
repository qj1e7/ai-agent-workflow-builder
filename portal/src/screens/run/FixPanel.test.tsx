import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import { fixKey, startedKey } from '../../api/fixQueries'
import { createDevSession } from '../../api/session'
import type { FixView } from '../../api/types'
import { FixSection } from './FixPanel'
import type { FixState } from './runModel'

const scope = createDevSession(null).cacheScope()
const ASKED = Date.parse('2026-11-04T02:20:00Z')
const ENDS = ASKED + 20 * 60_000
const BEFORE = ENDS - 1

const fix = (over: Partial<FixState> = {}): FixState => ({ id: 'fix_01FIRST', agents: [], ended: null, endsBy: ENDS as FixState['endsBy'], rounds: [], why: null, ...over })
const view = (over: Partial<FixView> = {}): FixView => ({
  fix_id: 'fix_01FIRST',
  run_id: 'run_01JB9',
  use_case_id: 'uc_01JB9',
  name: 'Release check',
  state: 'waiting',
  said: 'Waiting for a yes. Nothing changes until an Approver says yes.',
  asked_by: 'alice',
  asked_by_name: 'Alice',
  ends_by: new Date(ENDS).toISOString(),
  approval_id: 'apr_01A',
  question: null,
  can_turn_back_on: false,
  ...over,
})

interface Given {
  readonly fix?: FixState | null
  readonly view?: FixView
  readonly operator?: boolean
  readonly next?: 'retry' | 'report' | undefined
  readonly offer?: { can: boolean; why_not: string | null } | null
  readonly started?: FixView
  readonly approverId?: string | null
  readonly now?: number
}

function draw(given: Given = {}): string {
  const queryClient = new QueryClient()
  if (given.view) queryClient.setQueryData(fixKey(scope, given.view.fix_id), given.view)
  if (given.started) queryClient.setQueryData(startedKey(scope, 'run_01JB9'), given.started)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <FixSection
            runId="run_01JB9"
            fix={given.fix === undefined ? null : given.fix}
            operator={given.operator ?? true}
            next={'next' in given ? given.next : 'report'}
            offer={'offer' in given ? given.offer : CAN}
            approverId={given.approverId ?? null}
            now={given.now ?? BEFORE}
          />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const CAN = { can: true, why_not: null }
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const links = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [m[1], text(m[2] ?? '')])

describe('the button on a stopped run', () => {
  it('shows Fix it for me to an Operator, with what it does and does not do', () => {
    const html = draw()
    expect(buttons(html)).toEqual(['Fix it for me'])
    expect(text(html)).toContain('Nothing changes until an Approver says yes.')
  })

  it('shows an Approver why they can’t, and no button', () => {
    const html = draw({ operator: false })
    expect(buttons(html)).toEqual([])
    expect(text(html)).toBe('An Operator can ask for a fix.')
  })

  it('shows an Operator the platform’s reason when a fix can’t start, with no dead button', () => {
    const html = draw({ offer: { can: false, why_not: 'A fix for this workflow is already under way.' } })
    expect(buttons(html)).toEqual([])
    expect(text(html)).toBe('A fix for this workflow is already under way.')
  })

  it('shows nothing when fixes are off, before the platform has said, or on a stop a retry fixes', () => {
    expect(draw({ offer: { can: false, why_not: 'Fix it for me is off here.' } })).toBe('')
    expect(draw({ offer: null })).toBe('')
    expect(draw({ next: 'retry' })).toBe('')
  })

  it('hides the button once the press was answered, before the run’s own event arrives', () => {
    const started = view({ state: 'drafting', said: 'Drafting a fix. Nothing changes until an Approver says yes.', approval_id: null })
    const html = draw({ started })
    expect(buttons(html)).toEqual([])
    expect(text(html)).toBe('Drafting a fix. Nothing changes until an Approver says yes.')
  })
})

describe('progress under the stop', () => {
  it('says drafting from the activity until the platform answers, with no button', () => {
    const html = draw({ fix: fix() })
    expect(text(html)).toContain('Drafting a fix.')
    expect(buttons(html)).toEqual([])
  })

  it('says a ready fix waits for a yes in the platform’s words, with a way to the approval', () => {
    const html = draw({ fix: fix({ ended: 'proposed' }), view: view() })
    expect(text(html)).toContain('Waiting for a yes. Nothing changes until an Approver says yes.')
    expect(links(html)).toEqual([['/setup-approvals/apr_01A', 'Open the approval']])
    expect(buttons(html)).toEqual([])
  })

  it('gives an Approver who didn’t ask for it Review the fix as the one main button, and the person who asked the plain link', () => {
    const ready = { fix: fix({ ended: 'proposed' }), view: view(), operator: false }
    expect(links(draw({ ...ready, approverId: 'bob' }))).toEqual([['/setup-approvals/apr_01A', 'Review the fix']])
    expect(draw({ ...ready, approverId: 'bob' })).toMatch(/<a [^>]*class="[^"]*primary/)
    expect(links(draw({ ...ready, approverId: 'alice' }))).toEqual([['/setup-approvals/apr_01A', 'Open the approval']])
  })

  it('shows Turn back on only after the yes, to an Operator', () => {
    const approved = view({ state: 'approved', said: 'An Approver said yes. Turn it back on to try the fix with a test run, which writes nothing.', can_turn_back_on: true })
    expect(buttons(draw({ fix: fix({ ended: 'proposed' }), view: approved }))).toEqual(['Turn back on'])
    expect(buttons(draw({ fix: fix({ ended: 'proposed' }), view: approved, operator: false }))).toEqual([])
    expect(text(draw({ fix: fix({ ended: 'proposed' }), view: approved, operator: false }))).toContain('An Operator turns it back on.')
    expect(buttons(draw({ fix: fix({ ended: 'proposed' }), view: { ...approved, can_turn_back_on: false } }))).toEqual([])
  })

  it('shows the real test run, then each result in the platform’s words', () => {
    const states: [FixView['state'], string][] = [
      ['testing', 'Trying the fix with a test run, which writes nothing.'],
      ['on', 'The fix passed its test run, so the workflow is back on with it.'],
      ['test_failed', 'The test run didn’t pass, so the fix wasn’t turned on. The workflow stays as it was.'],
      ['declined', 'An Approver said no, so the fix stays off. The workflow stays as it was.'],
    ]
    for (const [state, said] of states) {
      const html = draw({ fix: fix({ ended: 'proposed' }), view: view({ state, said }) })
      expect(text(html)).toContain(said)
      expect(buttons(html)).toEqual(state === 'declined' ? ['Fix it for me'] : [])
    }
  })

  it('says a fix that ran out of time is over, and offers no spinner', () => {
    const html = draw({ fix: fix(), now: ENDS })
    expect(text(html)).not.toContain('Drafting')
    expect(text(html)).toContain("I couldn't fix this. Here's the cause and what I tried.")
    expect(text(html)).toContain('I reached the time limit for one fix.')
  })
})

describe('the hand-back card', () => {
  const back = fix({
    ended: 'handed_back',
    why: 'no_progress' as const,
    rounds: ['Round 1: 0 of 3 scenarios passed.', 'Round 2: 0 of 3 scenarios passed, no better than before.'],
  })

  it('says the team lead’s sentence, why it stopped and each round it tried', () => {
    const words = text(draw({ fix: back, view: view({ state: 'handed_back', said: "I couldn't fix this. Here's the cause and what I tried." }) }))
    expect(words).toContain("I couldn't fix this. Here's the cause and what I tried.")
    expect(words).toContain('A round made no progress.')
    expect(words).toContain('Round 1: 0 of 3 scenarios passed.')
    expect(words).toContain('Round 2: 0 of 3 scenarios passed, no better than before.')
    expect(words).not.toContain('Nothing was changed.')
  })

  it('says what the person can do next, and links the workflow', () => {
    const html = draw({ fix: back, view: view({ state: 'handed_back', approval_id: null }) })
    expect(text(html)).toContain('Open the workflow and change it yourself, or report this to support.')
    expect(links(html)).toEqual([['/workflows/uc_01JB9', 'Open the workflow']])
  })

  it('asks the one setting a fix never changes, with a button for each choice and one to type', () => {
    const question = {
      setting: 'repo',
      key: 'GitHub',
      words: 'Which repository should it read?',
      choices: [{ value: 'fastapi/fastapi', label: 'fastapi/fastapi' }],
      typed: 'Type another',
      waits: null,
    }
    const html = draw({ fix: back, view: view({ state: 'handed_back', approval_id: null, question }) })
    expect(text(html)).toContain('GitHub')
    expect(text(html)).toContain('Which repository should it read?')
    expect(buttons(html)).toEqual(['fastapi/fastapi', 'Type another'])
  })

  it('shows why it can’t be answered now, with no button for it', () => {
    const question = { setting: 'repo', key: 'GitHub', words: 'Which repository should it read?', choices: [], typed: null, waits: 'Waiting for an Operator to add a key' }
    const html = draw({ fix: back, view: view({ state: 'handed_back', approval_id: null, question }) })
    expect(text(html)).toContain('Waiting for an Operator to add a key')
    expect(buttons(html)).toEqual([])
  })

  it('shows someone who can’t answer a note in place of the buttons', () => {
    const question = { setting: 'repo', key: 'GitHub', words: 'Which repository should it read?', choices: [{ value: 'a/b', label: 'a/b' }], typed: 'Type another', waits: null }
    const html = draw({ fix: back, view: view({ state: 'handed_back', approval_id: null, question }), operator: false })
    expect(buttons(html)).toEqual([])
    expect(text(html)).toContain('Which repository should it read?')
    expect(text(html)).toContain('An Operator answers this.')
  })

  it('doesn’t offer another fix after a hand-back', () => {
    expect(buttons(draw({ fix: back, view: view({ state: 'handed_back', approval_id: null }) }))).toEqual([])
  })
})
