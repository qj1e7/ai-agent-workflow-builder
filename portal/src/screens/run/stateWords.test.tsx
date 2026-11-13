import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import decisions from '../../../../contracts/fixtures/approvals/decisions.bob.json'
import runUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import failure from '../../../../contracts/fixtures/runs/failure.json'
import rejected from '../../../../contracts/fixtures/runs/rejected.json'
import success from '../../../../contracts/fixtures/runs/success.json'
import troubleshooting from '../../../../contracts/fixtures/troubleshooting/failure.json'
import failedView from '../../../../contracts/fixtures/views/failure.final.json'
import workingView from '../../../../contracts/fixtures/views/failure.working.json'
import rejectedView from '../../../../contracts/fixtures/views/rejected.final.json'
import pendingView from '../../../../contracts/fixtures/views/scheduled.pending.json'
import waitingView from '../../../../contracts/fixtures/views/success.awaiting_approval.json'
import doneView from '../../../../contracts/fixtures/views/success.final.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { Me, PastDecisionView, RunView, TroubleshootingOut, UseCaseView } from '../../api/types'
import { decisionLine } from '../home/decided'
import { RunCardView } from '../home/RunCard'
import { RecentRuns } from '../workflows/RecentRuns'
import { emptyModel, foldWire, type RunModel } from './runModel'
import { RunPill } from './RunPill'
import { storyOf } from './useRunStory'
import { stageFactsOf, type RunState } from './words'

const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob' }
const nameOf = (id: string) => NAMES[id] ?? id
const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const NOW = new Date('2026-11-05T15:00:00+08:00')

const replay = (raw: readonly { run_id: string; seq: number }[], upTo = Infinity): RunModel => {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}
/** A run that ended where the line has no chat item for it: nobody answered, or n8n lost it. */
const endedAs = (model: RunModel, phase: RunModel['phase']): RunModel => ({ ...model, phase, reached: [...model.reached, { spot: { at: 'done' }, at: model.chat.at(-1)?.at ?? model.reached[0]?.at ?? (0 as RunModel['reached'][number]['at']) }] })
const view = (base: unknown, change: Record<string, unknown> = {}): RunView => ({ ...(base as object), ...change }) as RunView
const DECISION = decisions.decisions[1] as PastDecisionView

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const pills = (html: string) => [...html.matchAll(/<span class="[^"]*pill[^"]*"[^>]*>([^<]*)<\/span>/g)].map((match) => match[1])

function wrap(node: React.ReactNode): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>{node}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

function card(model: RunModel): string {
  const story = storyOf({
    run: { run_id: 'run_x', started_at: '2026-11-05T02:14:00Z' },
    live: { shown: model, head: model, loadedUpTo: model.seq },
    me: ALICE,
    nameOf,
    useCase: runUseCase as UseCaseView,
    approval: undefined,
    advice: troubleshooting as TroubleshootingOut,
    adviceLoading: false,
    modelOff: false,
    now: NOW,
  })
  return wrap(<RunCardView runId="run_x" name="LangGraph release check" story={story} beside={false} />)
}

interface Case {
  readonly state: RunState | 'nothing new'
  readonly model: RunModel
  readonly view: RunView
  readonly decision: Partial<PastDecisionView>
  readonly pill: string
  /** What each place says about it. Null for a stop: the card gives the troubleshooter's answers, and the decision record has no reason. */
  readonly words: RegExp | null
}

const CASES: readonly Case[] = [
  { state: 'pending', model: replay(success, 1), view: view(pendingView), decision: { run_state: 'pending', written: 0 }, pill: 'Running', words: /\bRunning\b/ },
  { state: 'working', model: replay(success, 6), view: view(workingView), decision: { run_state: 'working', written: 0 }, pill: 'Running', words: /\bRunning\b/ },
  { state: 'proposed', model: replay(success, 10), view: view(workingView, { state: 'proposed' }), decision: { run_state: 'proposed', written: 0 }, pill: 'Running', words: /\bRunning\b/ },
  { state: 'awaiting_approval', model: replay(success, 15), view: view(waitingView), decision: { run_state: 'awaiting_approval', written: 0 }, pill: 'Waiting for a yes', words: /Waiting for a yes/ },
  { state: 'acting', model: replay(success, 18), view: view(waitingView, { state: 'acting' }), decision: { run_state: 'acting', written: 0 }, pill: 'Running', words: /Creating the ticket/ },
  { state: 'succeeded', model: replay(success), view: view(doneView), decision: { run_state: 'succeeded', written: 1 }, pill: 'Done', words: /\b(1 ticket|MOCK-142) created\b/ },
  {
    state: 'nothing new',
    model: { ...replay(success), phase: { state: 'succeeded', outcome: 'nothing_to_write' }, written: [] },
    view: view(doneView, { outcome: 'nothing_to_write', written: [] }),
    decision: { run_state: 'succeeded', written: 0 },
    pill: 'Nothing new',
    words: /Nothing new to write/,
  },
  { state: 'rejected', model: replay(rejected), view: view(rejectedView), decision: { run_state: 'rejected', written: 0, declined_by: 'bob' }, pill: 'Declined', words: /Nothing was written\./ },
  { state: 'failed', model: replay(failure), view: view(failedView), decision: { run_state: 'failed', written: 0 }, pill: 'Stopped', words: null },
  {
    state: 'skipped',
    model: { ...replay(success, 6), phase: { state: 'skipped' } },
    view: view(failedView, { state: 'skipped', waiting_run_id: 'run_06' }),
    decision: { run_state: 'skipped', written: 0 },
    pill: 'Skipped',
    words: /Skipped\. An earlier run is still waiting for a yes\./,
  },
  { state: 'expired', model: endedAs(replay(success, 15), { state: 'expired' }), view: view(failedView, { state: 'expired' }), decision: { run_state: 'expired', written: 0 }, pill: 'No answer', words: /No answer\. Nothing was written\./ },
  {
    state: 'lost',
    model: endedAs(replay(success, 18), { state: 'lost' }),
    view: view(failedView, { state: 'lost' }),
    decision: { run_state: 'lost', written: 0 },
    pill: 'Lost',
    words: /Approved, but n8n lost the run\. Nothing was written\./,
  },
]

describe('one run state, the same words on the card, the panel, the chat’s decided card and Recent runs', () => {
  it('covers every state a run can be in', () => {
    const states: readonly RunState[] = ['pending', 'working', 'proposed', 'awaiting_approval', 'acting', 'succeeded', 'rejected', 'failed', 'skipped', 'expired', 'lost']
    expect(states.every((state) => CASES.some((one) => one.state === state))).toBe(true)
  })

  for (const one of CASES) {
    it(`${one.state}: one pill and one way of saying it`, () => {
      const onCard = card(one.model)
      const inPanel = wrap(<RunPill facts={stageFactsOf(one.model)} />)
      const row = wrap(<RecentRuns runs={[one.view]} now={NOW} nameOf={nameOf} firstRun={null} />)
      const decided = decisionLine({ ...DECISION, ...one.decision }, 'bob', NOW, nameOf)
      expect(pills(onCard), 'the card').toEqual([one.pill])
      expect(pills(inPanel), 'the panel and the page').toEqual([one.pill])
      expect(pills(row), 'Recent runs').toEqual([one.pill])
      if (one.words === null) return
      expect(text(onCard), 'the card').toMatch(one.words)
      expect(text(row), 'Recent runs').toMatch(one.words)
      expect(decided, 'the chat’s decided card').toMatch(one.words)
    })
  }
})
