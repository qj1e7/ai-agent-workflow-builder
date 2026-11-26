import type { ExplainReply, PlannerReply } from '../../api/types'
import type { PanelItem } from '../../ui/sidePanel'

/** What a choice on “Which workflow?” sends, so the Planner explains the one they picked. */
export const explainAsk = (name: string): string => `Explain the ${name}`

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
 * The workflow “explain it” means: the one open in the side panel, else the one the newest answer in the conversation named,
 * skipping answers that named none or several.
 */
export function workflowInFocus(panel: PanelItem | null, replies: readonly PlannerReply[]): string | null {
  if (panel?.kind === 'workflow') return panel.id
  for (const reply of replies.toReversed()) {
    const named = namedBy(reply)
    if (named !== null) return named
  }
  return null
}

export function explainAnswerOf(reply: ExplainReply, focus: string | null): { readonly kind: 'one'; readonly id: string; readonly name: string | null } | { readonly kind: 'which' | 'missing' } {
  if (reply.use_case_id !== null) return { kind: 'one', id: reply.use_case_id, name: reply.name }
  if (reply.missing !== null) return { kind: 'missing' }
  const focused = reply.in_focus ? reply.choices.find((choice) => choice.use_case_id === focus) : undefined
  return focused === undefined ? { kind: 'which' } : { kind: 'one', id: focused.use_case_id, name: focused.name }
}
