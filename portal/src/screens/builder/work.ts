import type { CardView, MissingTool, PlanOut } from '../../api/types'
import { startValues, type RunAgent } from './agentRun'
import { draftOf, type CardDraft } from './cardDraft'

/** What the panel beside the task shows. A new value remounts the form it holds. */
export type Work =
  | {
      readonly kind: 'run'
      readonly agents: readonly RunAgent[]
      /** The task the use case is saved with. */
      readonly instruction: string
      readonly intro: string
      readonly reason: string | null
      readonly questions: readonly string[]
    }
  | {
      readonly kind: 'editor'
      readonly draft: CardDraft
      /** The card to write a next version of. Null for a new card. */
      readonly cardId: string | null
      readonly intro: string
      readonly reason: string | null
      readonly questions: readonly string[]
      readonly missingTools: readonly MissingTool[]
    }
  | { readonly kind: 'cannot'; readonly reason: string; readonly missingTools: readonly MissingTool[] }
  | { readonly kind: 'model'; readonly message: string }

export const DRAFTED_WORDS = 'No saved agent fits, so the Room lead drafted one.'

function listed(names: readonly string[]): string {
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1) ?? ''}`
}

export function workOfPlan(plan: PlanOut, task: string): Work {
  switch (plan.decision) {
    case 'use_one':
    case 'use_several': {
      const agents = plan.agents.map((agent) => ({ card: agent.card, values: agent.values, missing: agent.missing }))
      return {
        kind: 'run',
        agents: agents.map((agent) => ({ ...agent, values: startValues(agent) })),
        instruction: task,
        intro: `The Room lead picked ${listed(plan.agents.map((agent) => agent.card.name))}.`,
        reason: plan.reason,
        questions: plan.questions,
      }
    }
    case 'new_agent':
      return {
        kind: 'editor',
        draft: draftOf(plan.draft),
        cardId: null,
        intro: DRAFTED_WORDS,
        reason: plan.reason,
        questions: plan.questions,
        missingTools: plan.missing_tools,
      }
    case 'cannot_do':
      return { kind: 'cannot', reason: plan.reason, missingTools: plan.missing_tools }
    case 'model_problem':
      return { kind: 'model', message: plan.message }
  }
}

/** A saved agent, ready to run. The examples fill the details, as they do for an agent from the library. */
export function runOfSaved(card: CardView, values: Readonly<Record<string, string>>, instruction: string): Work {
  return {
    kind: 'run',
    agents: [{ card, values, missing: [] }],
    instruction,
    intro: `Saved ${card.name}, version ${card.version}.`,
    reason: null,
    questions: [],
  }
}

export function editorOf(card: CardView, draft: CardDraft): Work {
  return {
    kind: 'editor',
    draft,
    cardId: card.starter ? null : card.card_id,
    intro: card.starter ? `${card.name} is a starter agent and cannot be changed. This is a copy.` : `Changing ${card.name}.`,
    reason: null,
    questions: [],
    missingTools: [],
  }
}
