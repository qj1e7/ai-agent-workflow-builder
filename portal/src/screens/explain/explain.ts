import { ApiError } from '../../api/client'
import type { ExplainReply, ExplainSetting, ExplainStep, ExplainTouch, ExplainWrite, PlannerReply, Segment, WorkflowExplained } from '../../api/types'
import type { PanelItem } from '../../ui/sidePanel'
import { andList, count } from '../run/words'

export const stepsGist = (steps: readonly ExplainStep[]): string => count(steps.length, 'block')

const ACTIONS = [
  ['reads', 'Reads'],
  ['writes', 'Writes'],
  ['posts', 'Posts'],
] as const

/** Each action with the systems it touches, once each, as “Reads GitHub and Jira · Writes Jira”. Where code can't tell the system, the place stands in. */
export function touchesGist(touches: readonly ExplainTouch[]): string {
  const parts = ACTIONS.flatMap(([action, label]) => {
    const here = touches.filter((touch) => touch.action === action)
    if (here.length === 0) return []
    const named = [...new Set(here.flatMap((touch) => touch.system ?? touch.place ?? []))]
    return [named.length === 0 ? label : `${label} ${andList(named)}`]
  })
  return parts.length === 0 ? 'Changes nothing' : parts.join(' · ')
}

/** What still needs someone first, then what code fixed and what passed. */
export function flagsGist(report: Pick<WorkflowExplained, 'flags' | 'fixed' | 'passed'>): string {
  const clearing = (...kinds: readonly string[]) => report.flags.filter((flag) => kinds.includes(flag.clears)).length
  const toFix = clearing('fixed_for_you', 'needs_a_setting', 'cant_run')
  const approver = clearing('approver_may_accept')
  const answers = clearing('needs_an_answer')
  const parts = [
    toFix > 0 ? `${String(toFix)} to fix` : '',
    approver > 0 ? `${String(approver)} for an Approver` : '',
    answers > 0 ? `${String(answers)} ${answers === 1 ? 'answer' : 'answers'} needed` : '',
    report.fixed.length > 0 ? `${String(report.fixed.length)} fixed for you` : '',
    report.passed.length > 0 ? `${String(report.passed.length)} passed` : '',
  ].filter(Boolean)
  return parts.length === 0 ? 'No flags' : parts.join(' · ')
}

export function approvesGist(approves: readonly ExplainWrite[]): string {
  if (approves.length === 0) return 'Writes nothing'
  const of = (decides: ExplainWrite['decides']) => approves.filter((write) => write.decides === decides).length
  const each = of('each_run')
  const parts = [
    each > 0 ? `${String(each)} ${each === 1 ? 'waits' : 'wait'} for a yes on each run` : '',
    of('set_up') > 0 ? `${String(of('set_up'))} on the set-up approval` : '',
    of('refused') > 0 ? `${String(of('refused'))} refused` : '',
    of('cant_run_yet') > 0 ? `${String(of('cant_run_yet'))} can’t run yet` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

export function settingsGist(settings: readonly ExplainSetting[]): string {
  const needed = settings.filter((setting) => setting.mark === 'needed').length
  const guessed = settings.filter((setting) => setting.mark === 'guessed').length
  const parts = [needed > 0 ? `${String(needed)} needed` : '', guessed > 0 ? `${String(guessed)} guessed` : ''].filter(Boolean)
  return parts.length === 0 ? count(settings.length, 'setting') : parts.join(' · ')
}

/** The approval's words lead with a short answer. The row shows that, and opens to the rest. */
export const approvalGist = (approval: string): string => /^[^.]*/.exec(approval)?.[0].trim() ?? approval

export const explainPath = (useCaseId: string, version: number | null): string =>
  `/workflows/${encodeURIComponent(useCaseId)}/explain${version === null ? '' : `?version=${String(version)}`}`

/** What a choice on “Which workflow?” sends, so the Planner explains the one she picked. */
export const explainAsk = (name: string): string => `Explain the ${name}`

export const explainTitle = (version: number | null): string => (version === null ? 'Explain' : `Explain, version ${String(version)}`)

/** The one workflow an answer was about, or null when it named none or several. */
function namedBy(reply: PlannerReply): string | null {
  switch (reply.answer) {
    case 'edit':
    case 'pause':
    case 'resume':
    case 'explain':
    case 'check_workflows':
    case 'why_stopped':
      return reply.use_case_id
    default:
      return null
  }
}

/**
 * The workflow “explain it” means: the one open in the side panel, whether as the workflow or as its Explain, else the one
 * the newest answer in the conversation named, skipping answers that named none or several.
 */
export function workflowInFocus(panel: PanelItem | null, replies: readonly PlannerReply[]): string | null {
  if (panel?.kind === 'workflow' || panel?.kind === 'explain') return panel.id
  for (const reply of replies.toReversed()) {
    const named = namedBy(reply)
    if (named !== null) return named
  }
  return null
}

const NO_WORDS = /^\s*(?:please\s+)?explain(?:\s+(?:it|this|that))?\s*[.!?]*\s*$/i

/** The request names no workflow: the Planner then answers with every workflow as a choice, so the one in focus can be explained. */
export const explainsFocus = (typed: string): boolean => NO_WORDS.test(typed)

export function explainAnswerOf(reply: ExplainReply, typed: string, focus: string | null): { readonly kind: 'one'; readonly id: string; readonly name: string | null } | { readonly kind: 'which' | 'missing' } {
  if (reply.use_case_id !== null) return { kind: 'one', id: reply.use_case_id, name: reply.name }
  if (reply.missing !== null) return { kind: 'missing' }
  if (reply.choices.length > 0 && explainsFocus(typed) && focus !== null) return { kind: 'one', id: focus, name: reply.choices.find((choice) => choice.use_case_id === focus)?.name ?? null }
  return { kind: 'which' }
}

/** The reworded In short is plain words with its quoted values in curly quotes, so it draws them as code's words do. */
export function segmentsOfText(text: string): Segment[] {
  return text
    .split(/(“[^”]*”)/)
    .filter((piece) => piece !== '')
    .map((piece) => (piece.startsWith('“') && piece.endsWith('”') ? { text: piece.slice(1, -1), quoted: true } : { text: piece, quoted: false }))
}

export type ExplainState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'report'; readonly report: WorkflowExplained }
  | { readonly kind: 'said'; readonly words: string }
  | { readonly kind: 'failed' }

/** A report, or the server's own words when it has nothing to explain (a workflow that is gone, a version that isn't there, a workflow on the shared n8n workflow), or a failed load. */
export function explainStateOf({ data, error }: { readonly data: WorkflowExplained | undefined; readonly error: unknown }): ExplainState {
  if (data !== undefined && error === null) return { kind: 'report', report: data }
  if (error === null || error === undefined) return { kind: 'loading' }
  if (error instanceof ApiError && (error.status === 404 || error.status === 409)) return { kind: 'said', words: error.message }
  return { kind: 'failed' }
}
