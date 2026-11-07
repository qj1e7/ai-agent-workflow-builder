import { ApiError } from '../../api/client'
import { failureReasonLabel } from '../../api/labels'
import { pressOnce, type Latch, type Outcome } from '../../api/latch'
import type { BlockKind, Me, RunView, ScheduleIn, UseCaseView } from '../../api/types'
import { agentIdentity } from '../../ui/agents'
import { andList, count, type NameOf } from '../run/words'
import { faceId } from '../agents/agents'
import { heldWords, repeatWords, TAKE_OVER_WORDS } from '../software/software'
import { nextRunAt, runWhen, zoneWords } from './times'

export type Tone = 'ok' | 'wait' | 'bad' | 'new'

export interface RunFact {
  readonly tone: Tone
  readonly pill: string | null
  readonly words: string
}

export interface Viewer {
  readonly id: string
  readonly operator: boolean
  readonly approver: boolean
}

export function lifeWords(state: UseCaseView['state']): string {
  return state === 'paused' ? 'Paused' : 'On'
}

function changesWaiting(run: Extract<RunView, { state: 'awaiting_approval' }>): string {
  const { actions } = run.proposal
  if (actions.length === 0) return 'Waiting for a yes.'
  const tickets = actions.every((action) => action.operation === 'create_ticket')
  const noun = count(actions.length, tickets ? 'ticket' : 'change')
  return `${noun} ${actions.length === 1 ? 'is' : 'are'} waiting for a yes.`
}

function doneWords(run: Extract<RunView, { state: 'succeeded' }>, nameOf: NameOf): string {
  if (run.outcome === 'nothing_to_write' || run.written.length === 0) return 'Done. Nothing to write.'
  const tickets = run.written.every((write) => write.operation === 'create_ticket')
  const what = tickets ? `${count(run.written.length, 'ticket')} created` : `${count(run.written.length, 'change')} written`
  const approvers = [...new Set(run.written.flatMap((write) => write.approved_by))].map(nameOf)
  return approvers.length > 0 ? `Done. ${what}, approved by ${andList(approvers)}.` : `Done. ${what}.`
}

const IN_PROGRESS: ReadonlySet<RunView['state']> = new Set(['pending', 'working', 'proposed', 'acting'])

/** The runs a row calls Running. Anything counting running workflows asks this, so a count never outruns the rows. */
export const isRunning = (run: RunView | null): boolean => run !== null && IN_PROGRESS.has(run.state)

export function runFact(run: RunView, nameOf: NameOf): RunFact {
  switch (run.state) {
    case 'awaiting_approval':
      return { tone: 'wait', pill: 'Needs a yes', words: changesWaiting(run) }
    case 'failed':
      return { tone: 'bad', pill: 'Stopped', words: `Stopped. ${failureReasonLabel[run.reason]}.` }
    case 'succeeded':
      return { tone: 'ok', pill: null, words: doneWords(run, nameOf) }
    case 'rejected':
      return { tone: 'ok', pill: null, words: `Declined by ${nameOf(run.rejected_by)}. Nothing was written.` }
    case 'pending':
    case 'working':
    case 'proposed':
    case 'acting':
      return { tone: 'new', pill: 'Running', words: 'Running now.' }
  }
}

export { formatterFactory, lineWhen, nextRunAt, runWhen, timesZone } from './times'

export function nextRunWords(useCase: Pick<UseCaseView, 'state' | 'next_run_at' | 'schedule'>, now: Date): string {
  if (useCase.state === 'paused') return 'Paused'
  if (useCase.schedule?.held) return 'Not running'
  return useCase.next_run_at ? nextRunAt(useCase.next_run_at, now, useCase.schedule?.time_zone) : 'Not scheduled'
}

/** Why the schedule starts no run while its owner can no longer run it, as the Software page says it. Paused wins, so null while paused. */
export function heldNote({ state, schedule }: Pick<UseCaseView, 'state' | 'schedule'>): string | null {
  return state === 'on' && schedule?.held ? heldWords(schedule.held, schedule.owner_name, TAKE_OVER_WORDS) : null
}

export interface When {
  readonly words: string
  readonly small: string
}

export function whenWords({ schedule }: Pick<UseCaseView, 'schedule'>): When {
  if (!schedule) return { words: 'No schedule', small: 'An Operator starts it with Run now.' }
  const words = repeatWords(schedule)
  return { words: words.charAt(0).toUpperCase() + words.slice(1), small: zoneWords(schedule.time_zone) }
}

const STEP_TAGS: Record<BlockKind, { readonly words: string; readonly writes: boolean }> = {
  agent: { words: 'Reads only', writes: false },
  approval: { words: 'Asks an Approver in Teams', writes: false },
  write_action: { words: 'Changes data, waits for a yes', writes: true },
}

export function stepTag(kind: BlockKind): { readonly words: string; readonly writes: boolean } {
  return STEP_TAGS[kind]
}

const newestFirst = (a: RunView, b: RunView) => b.started_at.localeCompare(a.started_at) || b.run_id.localeCompare(a.run_id)

export function runsOf(runs: readonly RunView[], useCaseId: string): RunView[] {
  return runs.filter((run) => run.use_case_id === useCaseId).sort(newestFirst)
}

export function latestRuns(runs: readonly RunView[]): ReadonlyMap<string, RunView> {
  const latest = new Map<string, RunView>()
  for (const run of runs) {
    const seen = latest.get(run.use_case_id)
    if (!seen || newestFirst(run, seen) < 0) latest.set(run.use_case_id, run)
  }
  return latest
}

export interface AgentLink {
  readonly face: string
  readonly name: string
  readonly to: string
}

const PLANNER: AgentLink = { face: 'planner', name: agentIdentity('planner').name, to: '/agents/planner' }
const VERSION_CHECKER_CARD = 'crd_version_checker'
const WATCHLIST_TEMPLATE = 'software_watchlist'
export const SOFTWARE_PAGE = '/software'

const looksAfterOnSoftwarePage = (useCase: Pick<UseCaseView, 'template'>) => useCase.template === WATCHLIST_TEMPLATE

export function workflowPath(useCase: Pick<UseCaseView, 'template' | 'use_case_id'>): string {
  return looksAfterOnSoftwarePage(useCase) ? SOFTWARE_PAGE : `/workflows/${useCase.use_case_id}`
}

export type Control = 'run' | 'pause' | 'resume' | 'delete'

/** Pause and Resume sit apart from the More actions menu, which holds Run now and Delete. */
export type Place = 'switch' | 'more'
export const PLACES_IN_PAGE_ORDER: readonly Place[] = ['switch', 'more']
const PLACE_OF: Record<Control, Place> = { run: 'more', pause: 'switch', resume: 'switch', delete: 'more' }
export const placeOf = (control: Control): Place => PLACE_OF[control]

/** Only an Operator changes a schedule. The Software watchlist's is changed on the Software page. */
export function mayChangeSchedule(useCase: Pick<UseCaseView, 'template'>, viewer: Viewer): boolean {
  return viewer.operator && !looksAfterOnSoftwarePage(useCase)
}

/** The toast after a save: when it runs next. The owner is named under When, so the toast does not repeat it. */
export function scheduleSavedWords(useCase: Pick<UseCaseView, 'state' | 'next_run_at' | 'schedule'>, now: Date): string {
  if (useCase.state === 'paused') return 'Saved. It runs on this schedule once you resume it.'
  return useCase.next_run_at ? `Saved. Next run ${nextRunAt(useCase.next_run_at, now, useCase.schedule?.time_zone)}.` : 'Saved.'
}

interface SavedAnswers {
  readonly onSuccess: (view: UseCaseView) => void
  readonly onError: (failure: unknown) => void
}

interface FormAnswers {
  readonly onSuccess: () => void
  readonly onError: (failure: unknown) => void
}

interface SaverTies {
  readonly useCaseId: string
  readonly now: Date
  readonly say: (words: string) => void
  readonly refocus: () => void
  readonly reread: (useCaseId: string) => void
}

/** What a save does with the platform's answer: close the form and say so, or show the refusal and, if the workflow changed or is gone, read it again. */
export function scheduleSaver(mutate: (body: ScheduleIn, answers: SavedAnswers) => void, { useCaseId, now, say, refocus, reread }: SaverTies) {
  const rereadIfOutOfDate = rereadWhenOutOfDate(useCaseId, refocus, reread)('schedule')
  return (body: ScheduleIn, form: FormAnswers): void =>
    mutate(body, {
      onSuccess: (view) => {
        form.onSuccess()
        say(scheduleSavedWords(view, now))
      },
      onError: (failure) => {
        form.onError(failure)
        rereadIfOutOfDate(failure)
      },
    })
}

/** What the More actions menu holds, in order. Delete is last. A workflow with none shows no menu. */
export type MenuAction = 'run' | 'schedule' | 'delete'

export function menuActionsOf(useCase: Pick<UseCaseView, 'template' | 'state'>, viewer: Viewer): readonly MenuAction[] {
  const controls = controlsOf(useCase, viewer)
  const actions: MenuAction[] = []
  if (controls.includes('run')) actions.push('run')
  if (mayChangeSchedule(useCase, viewer)) actions.push('schedule')
  if (controls.includes('delete')) actions.push('delete')
  return actions
}

export function controlsOf(useCase: Pick<UseCaseView, 'template' | 'state'>, viewer: Viewer): readonly Control[] {
  if (!viewer.operator || looksAfterOnSoftwarePage(useCase)) return []
  return useCase.state === 'paused' ? ['resume', 'delete'] : ['run', 'pause', 'delete']
}

export function agentsOf(useCase: Pick<UseCaseView, 'template' | 'agents'>): AgentLink[] {
  const cards: readonly { readonly card_id: string; readonly name: string }[] =
    useCase.template === WATCHLIST_TEMPLATE
      ? [{ card_id: VERSION_CHECKER_CARD, name: agentIdentity(faceId({ card_id: VERSION_CHECKER_CARD })).name }]
      : useCase.agents
  const unique = cards.filter((card, index) => cards.findIndex((other) => other.card_id === card.card_id) === index)
  return [PLANNER, ...unique.map((card) => ({ face: faceId(card), name: card.name, to: `/agents/${card.card_id}` }))]
}

export type RowAction = { readonly kind: 'decide' | 'why'; readonly runId: string }

/** The platform says whether the person can decide a waiting run. Only it knows who retried a run or is named on a step. */
export function rowAction(latest: RunView | null, viewer: Viewer): RowAction | null {
  if (!latest) return null
  if (latest.state === 'awaiting_approval') {
    return latest.you_can_decide ? { kind: 'decide', runId: latest.run_id } : null
  }
  if (latest.state === 'failed' && viewer.operator) return { kind: 'why', runId: latest.run_id }
  return null
}

export type Filter = 'all' | 'stopped' | 'paused'

export const FILTERS: readonly (readonly [Filter, string])[] = [
  ['all', 'All'],
  ['stopped', 'Stopped'],
  ['paused', 'Paused'],
]

export interface Row {
  readonly useCase: UseCaseView
  readonly latest: RunView | null
  readonly action: RowAction | null
}

function kept(row: Row, filter: Filter, words: string): boolean {
  if (words && !`${row.useCase.name} ${row.useCase.instruction}`.toLowerCase().includes(words)) return false
  switch (filter) {
    case 'all':
      return true
    case 'stopped':
      return row.latest?.state === 'failed'
    case 'paused':
      return row.useCase.state === 'paused'
  }
}

const NOTHING: ReadonlySet<string> = new Set()

/** A row's action is on its workflow's latest run. When Needs you already offers that run, the row keeps only its status, so no run is offered twice. */
export function rowsOf(
  useCases: readonly UseCaseView[],
  runs: readonly RunView[],
  viewer: Viewer,
  filter: Filter,
  query: string,
  runsInNeeds: ReadonlySet<string> = NOTHING,
): Row[] {
  const latest = latestRuns(runs)
  const words = query.trim().toLowerCase()
  const rows = useCases.map((useCase) => {
    const run = latest.get(useCase.use_case_id) ?? null
    const action = rowAction(run, viewer)
    return { useCase, latest: run, action: action && runsInNeeds.has(action.runId) ? null : action }
  })
  const needsYou = (row: Row) => (row.action ? 0 : 1)
  return rows.filter((row) => kept(row, filter, words)).sort((a, b) => needsYou(a) - needsYou(b))
}

export type RunNowOutcome = Outcome<{ readonly run_id: string }>

type Start = (input: { useCaseId: string; idempotencyKey: string }, outcome: RunNowOutcome) => void

interface RunNowAnswers {
  readonly open: (runId: string) => void
  readonly refused: (error: unknown) => void
}

/** The caller keeps one key until a run starts, so a press after a lost answer cannot start a second run. */
export function pressRunNow(latch: Latch, start: Start, input: { useCaseId: string; idempotencyKey: string }, { open, refused }: RunNowAnswers): void {
  pressOnce<{ readonly run_id: string }>(latch, (outcome) => start(input, outcome), { onSuccess: (started) => open(started.run_id), onError: refused })
}

export type Change = 'pause' | 'resume' | 'delete' | 'restore'

export type ChangeOutcome<T> = Outcome<T>

export const pressChange = pressOnce

export function changeWords(change: Change, useCase: Pick<UseCaseView, 'name' | 'state' | 'next_run_at'> & Partial<Pick<UseCaseView, 'schedule'>>, now: Date): string {
  switch (change) {
    case 'pause':
      return `Paused. ${useCase.name} won’t run until you resume it.`
    case 'resume':
      return useCase.next_run_at ? `Resumed. Next run ${nextRunAt(useCase.next_run_at, now, useCase.schedule?.time_zone)}.` : `Resumed. ${useCase.name} can run again.`
    case 'delete':
      return `Deleted ${useCase.name}.`
    case 'restore':
      return 'Put back.'
  }
}

const answered = (error: unknown, status: number) => error instanceof ApiError && error.status === status

export const meansOutOfDate = (error: unknown) => answered(error, 409) || answered(error, 404)

/** When the platform says the workflow changed or is gone, move focus off the pressed control and read it again. */
export const rereadWhenOutOfDate =
  <P>(useCaseId: string, refocus: (pressed: P) => void, reread: (useCaseId: string) => void) =>
  (pressed: P) =>
  (error: unknown): void => {
    if (!meansOutOfDate(error)) return
    refocus(pressed)
    reread(useCaseId)
  }

export const REFRESH_MS = 15_000

export function viewerOf(me: Me): Viewer {
  return { id: me.id, operator: me.roles.includes('operator'), approver: me.roles.includes('approver') }
}

export function changeProblem(change: Change, name: string, error: unknown, words: (error: unknown) => string): string {
  const start = change === 'restore' ? `Could not put ${name} back.` : `Could not ${change} ${name}.`
  if (change === 'restore' && answered(error, 410)) return `${start} It was deleted more than a day ago.`
  if (answered(error, 404)) return change === 'restore' ? `${start} The platform has no record of it.` : `${start} It was deleted.`
  return `${start} ${words(error)}`
}

export type BannerTone = 'ok' | 'wait' | 'bad' | 'off' | 'new'

export type BannerAction =
  | { readonly kind: 'decide'; readonly runId: string }
  | { readonly kind: 'stopped'; readonly runId: string; readonly retryable: boolean }
  | { readonly kind: 'resume' }

export interface Banner {
  readonly tone: BannerTone
  readonly text: string
  readonly action: BannerAction | null
}

interface BannerFacts {
  readonly useCase: Pick<UseCaseView, 'state' | 'next_run_at' | 'schedule'>
  readonly latest: RunView | null
  readonly viewer: Viewer
  readonly now: Date
  readonly nameOf: NameOf
}

const atWords = (when: string) => when.replace(/^Today, /, 'today at ').replace(/^(.+), (\d+:\d+)$/, '$1 at $2')

/** One sentence on the state, and the one action that moves it on. Pause wins over the latest run, because a paused workflow starts nothing. */
export function bannerOf({ useCase, latest, viewer, now, nameOf }: BannerFacts): Banner {
  if (useCase.state === 'paused') {
    return { tone: 'off', text: 'Paused. It won’t run until you resume it.', action: viewer.operator ? { kind: 'resume' } : null }
  }
  if (latest?.state === 'awaiting_approval') {
    return { tone: 'wait', text: runFact(latest, nameOf).words, action: latest.you_can_decide ? { kind: 'decide', runId: latest.run_id } : null }
  }
  if (latest?.state === 'failed') {
    return {
      tone: 'bad',
      text: `Stopped ${atWords(runWhen(latest.started_at, now))}. ${failureReasonLabel[latest.reason]}.`,
      action: viewer.operator ? { kind: 'stopped', runId: latest.run_id, retryable: latest.retryable } : null,
    }
  }
  if (latest && runFact(latest, nameOf).tone === 'new') return { tone: 'new', text: 'Running now.', action: null }
  const held = heldNote(useCase)
  if (held) return { tone: 'ok', text: held, action: null }
  if (!useCase.schedule) return { tone: 'ok', text: 'On. It has no schedule, so it runs when an Operator presses Run now.', action: null }
  return { tone: 'ok', text: `On. Next run ${nextRunWords(useCase, now)}.`, action: null }
}

/** What Delete takes away, said before the person confirms. */
export function deleteWords(name: string, pastRuns: number | null): string {
  const kept = pastRuns === null ? '' : pastRuns === 0 ? ' It has no runs yet.' : ` ${pastRuns === 1 ? 'Its 1 past run stays' : `Its ${pastRuns} past runs stay`} in the record, with who approved what.`
  return `${name} leaves Workflows, and its schedule stops, so no more runs start.${kept} Undo stays in the message that follows.`
}
