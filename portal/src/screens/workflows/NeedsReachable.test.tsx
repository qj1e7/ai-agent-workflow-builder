import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import aliceHome from '../../../../contracts/fixtures/builder/home.alice.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import failed from '../../../../contracts/fixtures/views/failure.final.json'
import waiting from '../../../../contracts/fixtures/views/success.awaiting_approval.json'
import done from '../../../../contracts/fixtures/views/success.final.json'
import { App } from '../../App'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ApprovalItem, ConfirmationItem, FollowingUpItem, HomeOut, Me, ReplyView, RunView, StoppedItem, UseCaseView } from '../../api/types'

const PEOPLE: Record<'alice' | 'bob' | 'carol', Me> = {
  alice: { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] },
  bob: { id: 'bob', display: 'Bob', roles: ['approver'] },
  carol: { id: 'carol', display: 'Carol', roles: ['operator'] },
}
const API_SHOWN = 10
const NOW = new Date('2026-11-04T15:00:00+08:00')
const BASE = Date.parse('2026-11-01T00:00:00Z')

type Kind = 'decide' | 'others' | 'stopped' | 'done'

interface Made {
  readonly workflow: number
  readonly kind: Kind
  readonly minute: number
  readonly party?: boolean
  readonly retryable?: boolean
}

interface Situation {
  readonly name: string
  readonly me: Me
  readonly workflows: number
  readonly runs: readonly Made[]
  readonly confirmations: readonly ConfirmationItem['kind'][]
  readonly replies?: number
}

const operator = (me: Me) => me.roles.includes('operator')
const approver = (me: Me) => me.roles.includes('approver')
const workflowId = (n: number) => `uc_${String(n).padStart(2, '0')}`
const runId = (index: number) => `run_${String(index).padStart(3, '0')}`
const iso = (minute: number) => new Date(BASE + minute * 60_000).toISOString()

interface Run {
  readonly view: RunView
  readonly made: Made
}

function runsOf({ me, runs }: Situation): Run[] {
  return runs.map((made, index) => {
    const ids = { run_id: runId(index), use_case_id: workflowId(made.workflow), use_case_name: `Workflow ${made.workflow}`, started_at: iso(made.minute) }
    switch (made.kind) {
      case 'decide':
      case 'others':
        return { made, view: { ...(waiting as RunView), ...ids, you_can_decide: made.kind === 'decide' && approver(me) } as RunView }
      case 'stopped':
        return { made, view: { ...(failed as RunView), ...ids, retryable: made.retryable ?? true } as RunView }
      case 'done':
        return { made, view: { ...(done as RunView), ...ids } }
    }
  })
}

const newestFirst = (a: Run, b: Run) => b.view.started_at.localeCompare(a.view.started_at) || b.view.run_id.localeCompare(a.view.run_id)

function latestOf(runs: readonly Run[]): Map<string, Run> {
  const latest = new Map<string, Run>()
  for (const run of [...runs].sort(newestFirst)) if (!latest.has(run.view.use_case_id)) latest.set(run.view.use_case_id, run)
  return latest
}

const youDecide = (run: Run) => run.view.state === 'awaiting_approval' && run.view.you_can_decide === true

/** What GET /api/v1/home answers this person, worked out as platform-api does it (builder/home.py, orchestration/person_runs.py, open_runs in orchestration/store.py): each kind newest first and cut at 10, with the totals. */
function platformHome(situation: Situation, runs: readonly Run[]): HomeOut {
  const base = aliceHome as HomeOut
  const latest = latestOf(runs)
  const asks = runs.filter(youDecide).sort(newestFirst)
  const stops = runs
    .filter((run) => run.view.state === 'failed' && latest.get(run.view.use_case_id) === run && operator(situation.me) && run.made.party !== false)
    .sort(newestFirst)
  const approvalShape = (bobHome as HomeOut).approvals[0] as ApprovalItem
  const stoppedShape = base.stopped[0] as StoppedItem
  const confirmationShape = (bobHome as HomeOut).confirmations[0] as ConfirmationItem
  const replyShape = base.replied[0] as FollowingUpItem
  return {
    ...base,
    approvals: asks.slice(0, API_SHOWN).map(({ view }) => ({ ...approvalShape, run_id: view.run_id, approval_id: `apr_${view.run_id}`, use_case_id: view.use_case_id, use_case_name: view.use_case_name, started_by: 'carol', started_by_name: 'Carol', started_at: view.started_at })),
    approvals_total: asks.length,
    stopped: stops.slice(0, API_SHOWN).map(({ view, made }) => ({ ...stoppedShape, run_id: view.run_id, use_case_id: view.use_case_id, use_case_name: view.use_case_name, started_at: view.started_at, stopped_at: view.started_at, retryable: made.retryable ?? true })),
    stopped_total: stops.length,
    confirmations: approver(situation.me)
      ? situation.confirmations.map((kind, n) => ({ ...confirmationShape, confirmation_id: `cfm_${n}`, kind, about_name: kind === 'approver' ? `Person ${n}` : null }))
      : [],
    waiting_on_others: [],
    waiting_on_others_total: 0,
    replied: Array.from({ length: situation.replies ?? 0 }, (_, n) => ({ ...replyShape, request_id: `trq_${n}`, asked_at: iso(n), latest_reply: { ...(replyShape.latest_reply as ReplyView), replied_at: iso(n + 5) } })),
  }
}

function render(situation: Situation, runs: readonly Run[], home: HomeOut): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  const useCases: UseCaseView[] = Array.from({ length: situation.workflows }, (_, n) => ({ ...(agentUseCase as UseCaseView), use_case_id: workflowId(n), name: `Workflow ${n}` }))
  queryClient.setQueryData(['me', scope], situation.me)
  queryClient.setQueryData(['dev-users'], Object.values(PEOPLE))
  queryClient.setQueryData(['runs', scope], runs.map((run) => run.view))
  queryClient.setQueryData(['home', scope], home)
  queryClient.setQueryData(['use-cases', scope], useCases)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter initialEntries={[{ pathname: '/workflows' }]}>
          <App now={() => NOW} />
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

interface Control {
  readonly href: string | null
  readonly primary: boolean
  readonly text: string
  readonly item: string | null
}

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'])

/** Every link and button in the page's main region, with the Needs you item it sits in. */
function controlsOf(html: string): Control[] {
  const main = /<main\b[\s\S]*<\/main>/.exec(html)?.[0] ?? ''
  const open: (string | null)[] = []
  const controls: Control[] = []
  let current: { readonly from: number; readonly attrs: string; readonly item: string | null } | null = null
  for (const tag of main.matchAll(/<(\/?)([a-zA-Z][\w-]*)([^>]*)>/g)) {
    const [whole, closing, name = '', attrs = ''] = tag
    if (closing) {
      if (current && (name === 'a' || name === 'button')) {
        const text = main.slice(current.from, tag.index).replace(/<[^>]*>/g, '').trim()
        controls.push({ href: /\bhref="([^"]*)"/.exec(current.attrs)?.[1] ?? null, primary: /\bclass="[^"]*_primary_/.test(current.attrs), text, item: current.item })
        current = null
      }
      open.pop()
      continue
    }
    const item = /\bdata-home-item="([^"]*)"/.exec(attrs)?.[1] ?? open.at(-1) ?? null
    if (name === 'a' || name === 'button') current = { from: tag.index + whole.length, attrs, item }
    if (!VOID.has(name) && !attrs.endsWith('/')) open.push(item)
  }
  return controls
}

/** The run a control acts on: a link that opens it, or Retry inside its stopped item. */
function actionOf(control: Control): string | null {
  const opens = /^\/runs\/([^/?#]+)$/.exec(control.href ?? '')?.[1]
  if (opens) return `open ${opens}`
  const stopped = /^stopped:(.+)$/.exec(control.item ?? '')?.[1]
  return stopped && control.href === null ? `retry ${stopped}` : null
}

interface Seen {
  readonly situation: Situation
  readonly runs: readonly Run[]
  readonly home: HomeOut
  readonly controls: readonly Control[]
  readonly actions: readonly string[]
}

function see(situation: Situation): Seen {
  const runs = runsOf(situation)
  const home = platformHome(situation, runs)
  const controls = controlsOf(render(situation, runs, home))
  return { situation, runs, home, controls, actions: controls.map(actionOf).filter((action): action is string => action !== null) }
}

const reaches = (seen: Seen, run: string) => seen.actions.includes(`open ${run}`) || seen.actions.includes(`retry ${run}`)

function describeSituation({ situation, home }: Seen): string {
  const shape = `${situation.me.id}, ${situation.workflows} workflows, API returned ${home.approvals.length} of ${home.approvals_total} approvals, ${home.stopped.length} of ${home.stopped_total} stopped, ${home.confirmations.length} confirmations, ${home.replied.length} replies`
  return `${situation.name} (${shape})`
}

function unreachable(seen: Seen): string[] {
  const { home, runs, controls } = seen
  const newerOnSameWorkflow = (run: string, workflow: string) => {
    const mine = runs.find((r) => r.view.run_id === run)
    const newer = runs.filter((r) => r.view.use_case_id === workflow && mine && newestFirst(r, mine) < 0).map((r) => r.view.run_id)
    return newer.length ? `, older than ${newer.join(' and ')} on the same workflow` : ''
  }
  return [
    ...home.approvals.filter((item) => !reaches(seen, item.run_id)).map((item) => `approval ${item.approval_id} (run ${item.run_id}, ${item.use_case_id}${newerOnSameWorkflow(item.run_id, item.use_case_id)}): no button acts on its run`),
    ...home.stopped.filter((item) => !reaches(seen, item.run_id)).map((item) => `stopped run ${item.run_id} (${item.use_case_id}): no button acts on it`),
    ...home.confirmations.filter((item) => !controls.some((control) => control.item === `confirmation:${item.confirmation_id}`)).map((item) => `confirmation ${item.confirmation_id}: no button`),
    ...home.replied.filter((item) => !controls.some((control) => control.item === `reply:${item.request_id}` && control.href === `/workflows?request=${item.request_id}`)).map((item) => `reply to request ${item.request_id}: no button opens it`),
  ]
}

/** A workflow's own action is on its latest run: Review and decide when you may decide it, or See why it stopped for an Operator. */
function deadEnds(seen: Seen): string[] {
  return [...latestOf(seen.runs).values()]
    .filter((run) => youDecide(run) || (run.view.state === 'failed' && operator(seen.situation.me)))
    .filter((run) => !reaches(seen, run.view.run_id))
    .map((run) => `${run.view.use_case_id}: its latest run ${run.view.run_id} (${run.view.state}) has no button anywhere`)
}

function twice({ actions }: Seen): string[] {
  return [...new Set(actions.filter((action, index) => actions.indexOf(action) !== index))].map((action) => `"${action}" is offered more than once`)
}

function primaryProblem({ controls, actions, home }: Seen): string[] {
  const primaries = controls.filter((control) => control.primary).map((control) => control.text)
  const somethingToDo = actions.length > 0 || home.confirmations.length > 0 || home.replied.length > 0
  const expected = somethingToDo ? 1 : 0
  return primaries.length === expected ? [] : [`${primaries.length} primary buttons (${primaries.join(', ')}), expected ${expected}`]
}

/** A small seeded generator, so a failing situation is the same on every run. */
function random(seed: number): () => number {
  let state = seed
  return () => {
    state = (state + 0x6d2b79f5) | 0
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function generated(count: number): Situation[] {
  const next = random(141)
  const upTo = (n: number) => Math.floor(next() * (n + 1))
  const shuffled = (n: number) => {
    const out = Array.from({ length: n }, (_, i) => i)
    for (let i = n - 1; i > 0; i -= 1) {
      const j = upTo(i)
      ;[out[i], out[j]] = [out[j] ?? j, out[i] ?? i]
    }
    return out
  }
  const who = [PEOPLE.alice, PEOPLE.alice, PEOPLE.bob, PEOPLE.carol]
  return Array.from({ length: count }, (_, n): Situation => {
    const workflows = 1 + upTo(13)
    const anyWorkflow = () => upTo(workflows - 1)
    const failing = shuffled(workflows)
    const runs: Made[] = [
      ...Array.from({ length: upTo(12) }, (): Made => ({ workflow: anyWorkflow(), kind: 'decide', minute: upTo(999) })),
      ...Array.from({ length: upTo(12) }, (_, i): Made => ({ workflow: failing[i] ?? anyWorkflow(), kind: 'stopped', minute: upTo(999) + (next() < 0.7 ? 1000 : 0), party: next() < 0.85, retryable: next() < 0.6 })),
      ...Array.from({ length: upTo(3) }, (): Made => ({ workflow: anyWorkflow(), kind: 'others', minute: upTo(999) })),
      ...Array.from({ length: upTo(4) }, (): Made => ({ workflow: anyWorkflow(), kind: 'done', minute: upTo(999) })),
    ]
    const confirmations = Array.from({ length: upTo(2) }, (): ConfirmationItem['kind'] => (next() < 0.5 ? 'approver' : 'model_address'))
    return { name: `generated #${n}`, me: who[upTo(who.length - 1)] ?? PEOPLE.alice, workflows, runs, confirmations, replies: n % 5 === 0 ? 1 : n % 7 === 0 ? 2 : 0 }
  })
}

const own = (first: number, count: number, kind: Kind, minute: (i: number) => number): Made[] => Array.from({ length: count }, (_, i) => ({ workflow: first + i, kind, minute: minute(i) }))

const NAMED: Situation[] = [
  {
    name: 'the live re-check: a stopped run, then 9 approvals including the newer request on workflow 0, so the older one is the 10th',
    me: PEOPLE.alice,
    workflows: 21,
    runs: [
      { workflow: 0, kind: 'decide', minute: 100 },
      ...own(1, 8, 'decide', (i) => 110 + i),
      { workflow: 0, kind: 'decide', minute: 190 },
      ...own(9, 10, 'decide', (i) => i),
      { workflow: 20, kind: 'stopped', minute: 200 },
    ],
    confirmations: [],
  },
  {
    name: 'an older approval in Needs you while the same workflow’s newer run stopped, out of the platform’s stopped list',
    me: PEOPLE.alice,
    workflows: 2,
    runs: [
      { workflow: 0, kind: 'decide', minute: 10 },
      { workflow: 0, kind: 'stopped', minute: 20, party: false },
      { workflow: 1, kind: 'done', minute: 5 },
    ],
    confirmations: [],
  },
  { name: 'an Approver only, with 12 approvals and two confirmations', me: PEOPLE.bob, workflows: 12, runs: own(0, 12, 'decide', (i) => i), confirmations: ['approver', 'model_address'] },
  { name: 'twelve stopped runs, so the platform returns ten, and two approvals', me: PEOPLE.alice, workflows: 14, runs: [...own(0, 12, 'stopped', (i) => 100 + i), ...own(12, 2, 'decide', (i) => i)], confirmations: [] },
  { name: 'nothing needs anyone', me: PEOPLE.alice, workflows: 3, runs: own(0, 3, 'done', (i) => i), confirmations: [] },
  { name: 'only a reply from the team', me: PEOPLE.bob, workflows: 3, runs: own(0, 3, 'done', (i) => i), confirmations: [], replies: 1 },
  { name: 'two replies, an approval and a stop', me: PEOPLE.alice, workflows: 4, runs: [...own(0, 1, 'decide', () => 5), ...own(1, 1, 'stopped', () => 9)], confirmations: ['approver'], replies: 2 },
]

const SITUATIONS = [...NAMED, ...generated(240)].map(see)

function failing(check: (seen: Seen) => string[]): { readonly failing: number; readonly first: readonly string[] } {
  const found = SITUATIONS.map((seen) => ({ seen, problems: check(seen) })).filter(({ problems }) => problems.length > 0)
  return { failing: found.length, first: found.slice(0, 3).map(({ seen, problems }) => `${describeSituation(seen)}: ${problems.join('; ')}`) }
}

const NONE = { failing: 0, first: [] }

describe(`Needs you on Workflows, in ${SITUATIONS.length} situations the platform can return`, () => {
  it('covers the shapes that matter: more than 10 returned, older and newer requests on one workflow, lists the platform cut, an Approver only, confirmations', () => {
    const count = (test: (seen: Seen) => boolean) => SITUATIONS.filter(test).length
    const shapes = {
      moreThanTenReturned: count(({ home }) => home.approvals.length + home.stopped.length + home.confirmations.length > 10),
      severalRequestsOnOneWorkflow: count(({ home }) => new Set(home.approvals.map((item) => item.use_case_id)).size < home.approvals.length),
      approvalsCutByThePlatform: count(({ home }) => home.approvals_total > home.approvals.length),
      stoppedCutByThePlatform: count(({ home }) => home.stopped_total > home.stopped.length),
      nothingInNeedsYouButARowToAct: count(({ home, runs, situation }) => home.approvals_total + home.stopped_total + home.confirmations.length === 0 && [...latestOf(runs).values()].some((run) => youDecide(run) || (run.view.state === 'failed' && operator(situation.me)))),
      approverOnly: count(({ situation }) => !operator(situation.me)),
      replies: count(({ home }) => home.replied.length > 0),
      confirmations: count(({ home }) => home.confirmations.length > 0),
      nothingToDo: count(({ actions, home }) => actions.length === 0 && home.confirmations.length === 0 && home.replied.length === 0),
    }
    for (const [shape, n] of Object.entries(shapes)) expect(n, shape).toBeGreaterThanOrEqual(1)
    expect(shapes.moreThanTenReturned).toBeGreaterThanOrEqual(30)
    expect(shapes.severalRequestsOnOneWorkflow).toBeGreaterThanOrEqual(30)
  })

  it('reaches every item the platform returns by a button that acts on that exact run', () => {
    expect(failing(unreachable)).toEqual(NONE)
  })

  it('keeps each workflow’s own action somewhere on the page', () => {
    expect(failing(deadEnds)).toEqual(NONE)
  })

  it('never offers the same run twice', () => {
    expect(failing(twice)).toEqual(NONE)
  })

  it('has one primary button when there is something to do, and none when there is nothing', () => {
    expect(failing(primaryProblem)).toEqual(NONE)
  })
})
