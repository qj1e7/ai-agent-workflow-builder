import { ApiError } from '../../api/client'
import { failureReasonLabel } from '../../api/labels'
import type { Latch } from '../../api/latch'
import type { BlockKind, RunView, UseCaseView } from '../../api/types'
import type { FaceState } from '../../ui/AgentFace'
import { agentIdentity } from '../../ui/agents'
import { andList, count, type NameOf } from '../run/words'
import { faceId } from '../agents/agents'
import { repeatWords } from '../software/software'

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

const TIME_ZONE = 'Asia/Singapore'
const parts = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: TIME_ZONE,
})

interface Moment {
  readonly weekday: string
  readonly day: string
  readonly month: string
  readonly year: string
  readonly clock: string
}

function momentOf(at: Date): Moment {
  const all = parts.formatToParts(at)
  const part = (type: Intl.DateTimeFormatPartTypes) => all.find((p) => p.type === type)?.value ?? ''
  return { weekday: part('weekday'), day: part('day'), month: part('month'), year: part('year'), clock: `${Number(part('hour'))}:${part('minute')}` }
}

function dayWords(at: Moment, now: Moment): string {
  const date = `${at.weekday} ${at.day} ${at.month}`
  return at.year === now.year ? date : `${date} ${at.year}`
}

const sameDay = (a: Moment, b: Moment) => a.day === b.day && a.month === b.month && a.year === b.year

/** "Today, 10:14", "Tue 3 Nov, 10:14" or "Mon 4 Jan 2027, 9:00", in Singapore time. */
export function runWhen(iso: string, now: Date): string {
  const at = momentOf(new Date(iso))
  const today = momentOf(now)
  return `${sameDay(at, today) ? 'Today' : dayWords(at, today)}, ${at.clock}`
}

/** The list's shorter form: "Today 10:14", or the date alone. */
export function lineWhen(iso: string, now: Date): string {
  const at = momentOf(new Date(iso))
  const today = momentOf(now)
  return sameDay(at, today) ? `Today ${at.clock}` : dayWords(at, today)
}

export function nextRunWords(useCase: Pick<UseCaseView, 'state' | 'next_run_at'>, now: Date): string {
  if (useCase.state === 'paused') return 'Paused'
  return useCase.next_run_at ? runWhen(useCase.next_run_at, now) : 'Not scheduled'
}

export interface When {
  readonly words: string
  readonly small: string
}

export function whenWords({ schedule }: Pick<UseCaseView, 'schedule'>): When {
  if (!schedule) return { words: 'No schedule', small: 'An Operator starts it with Run now.' }
  const words = repeatWords(schedule)
  return { words: words.charAt(0).toUpperCase() + words.slice(1), small: 'Singapore time (SGT).' }
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

/** Where each control sits on the workflow page, in page order. Pause and Resume are one button. */
export type Place = 'run' | 'switch' | 'delete'
export const PLACES: readonly Place[] = ['run', 'switch', 'delete']
const PLACE_OF: Record<Control, Place> = { run: 'run', pause: 'switch', resume: 'switch', delete: 'delete' }
export const placeOf = (control: Control): Place => PLACE_OF[control]

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

export function faceStates(useCase: Pick<UseCaseView, 'state'>, latest: RunView | null, total: number): FaceState[] {
  const proposer = total - 1
  return Array.from({ length: total }, (_, index): FaceState => {
    if (useCase.state === 'paused') return 'stopped'
    return latest?.state === 'awaiting_approval' && index === proposer ? 'waiting' : 'idle'
  })
}

export type RowAction = { readonly kind: 'decide' | 'why'; readonly runId: string }

function mayDecide(useCase: Pick<UseCaseView, 'owner'>, run: Pick<RunView, 'started_by'>, viewer: Viewer): boolean {
  const party = run.started_by === viewer.id || useCase.owner === viewer.id
  return viewer.approver && !party
}

export function rowAction(useCase: Pick<UseCaseView, 'owner'>, latest: RunView | null, viewer: Viewer): RowAction | null {
  if (!latest) return null
  if (latest.state === 'awaiting_approval') {
    return mayDecide(useCase, latest, viewer) ? { kind: 'decide', runId: latest.run_id } : null
  }
  if (latest.state === 'failed' && viewer.operator) return { kind: 'why', runId: latest.run_id }
  return null
}

export type Filter = 'all' | 'needs' | 'stopped' | 'paused'

export const FILTERS: readonly (readonly [Filter, string])[] = [
  ['all', 'All'],
  ['needs', 'Needs you'],
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
    case 'needs':
      return row.action !== null
    case 'stopped':
      return row.latest?.state === 'failed'
    case 'paused':
      return row.useCase.state === 'paused'
  }
}

export function rowsOf(useCases: readonly UseCaseView[], runs: readonly RunView[], viewer: Viewer, filter: Filter, query: string): Row[] {
  const latest = latestRuns(runs)
  const words = query.trim().toLowerCase()
  const rows = useCases.map((useCase) => {
    const run = latest.get(useCase.use_case_id) ?? null
    return { useCase, latest: run, action: rowAction(useCase, run, viewer) }
  })
  const needsYou = (row: Row) => (row.action ? 0 : 1)
  return rows.filter((row) => kept(row, filter, words)).sort((a, b) => needsYou(a) - needsYou(b))
}

export interface RunNowOutcome {
  onSuccess?: (started: { readonly run_id: string }) => void
  onError?: (error: unknown) => void
  onSettled?: () => void
}

type Start = (input: { useCaseId: string; idempotencyKey: string }, outcome: RunNowOutcome) => void

interface RunNowAnswers {
  readonly open: (runId: string) => void
  readonly refused: (error: unknown) => void
}

/** The caller keeps one key until a run starts, so a press after a lost answer cannot start a second run. */
export function pressRunNow(latch: Latch, start: Start, input: { useCaseId: string; idempotencyKey: string }, { open, refused }: RunNowAnswers): void {
  latch.run((settled) => start(input, { onSuccess: (started) => open(started.run_id), onError: refused, onSettled: settled }))
}

export type Change = 'pause' | 'resume' | 'delete' | 'restore'

export interface ChangeOutcome<T> {
  onSuccess?: (value: T) => void
  onError?: (error: unknown) => void
  onSettled?: () => void
}

export function pressChange<T>(latch: Latch, send: (outcome: ChangeOutcome<T>) => void, outcome: ChangeOutcome<T>): void {
  latch.run((settled) =>
    send({
      ...outcome,
      onSettled: () => {
        settled()
        outcome.onSettled?.()
      },
    }),
  )
}

export function changeWords(change: Change, useCase: Pick<UseCaseView, 'name' | 'state' | 'next_run_at'>, now: Date): string {
  switch (change) {
    case 'pause':
      return `Paused. ${useCase.name} won’t run until you resume it.`
    case 'resume':
      return useCase.next_run_at ? `Resumed. Next run ${runWhen(useCase.next_run_at, now)}.` : `Resumed. ${useCase.name} can run again.`
    case 'delete':
      return `Deleted ${useCase.name}.`
    case 'restore':
      return 'Put back.'
  }
}

const answered = (error: unknown, status: number) => error instanceof ApiError && error.status === status

export const meansOutOfDate = (error: unknown) => answered(error, 409) || answered(error, 404)

export function changeProblem(change: Change, name: string, error: unknown, words: (error: unknown) => string): string {
  const start = change === 'restore' ? `Could not put ${name} back.` : `Could not ${change} ${name}.`
  if (change === 'restore' && answered(error, 410)) return `${start} It was deleted more than a day ago.`
  if (answered(error, 404)) return change === 'restore' ? `${start} The platform has no record of it.` : `${start} It was deleted.`
  return `${start} ${words(error)}`
}
