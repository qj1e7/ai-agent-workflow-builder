import { andList, sentence, stageFactsOf, stageWords, type NameOf } from './words'
import type { RunModel } from './runModel'

export interface Answer {
  readonly label: string
  readonly text: string
}

/**
 * What the AI troubleshooter says about a run that is no longer stopped, from the run's own events: what the agents found, then where
 * it is now, in stageWords' words. A stopped run's three answers come from the troubleshooter itself (Outcome.tsx). A run that has ended
 * has none: the settled line under its steps says the result once.
 */
export function stageAnswers(model: RunModel, found: string, nameOf: NameOf): readonly Answer[] {
  const foundRow: Answer[] = found === '' ? [] : [{ label: 'Found', text: found }]
  const facts = stageFactsOf(model)
  const words = stageWords(facts, nameOf)
  const now = (text: string): Answer => ({ label: 'Now', text })
  switch (facts.state) {
    case 'failed':
    case 'succeeded':
    case 'rejected':
    case 'expired':
    case 'lost':
      return []
    case 'pending':
    case 'working':
    case 'proposed':
      return [now(facts.retried ? `${words} after a short wait…` : `${words}…`)]
    case 'awaiting_approval':
      return [...foundRow, now(sentence(words))]
    case 'acting': {
      const yes = facts.approvedBy.length > 0 ? `${andList(facts.approvedBy.map(nameOf))} said yes` : 'It was approved'
      return [...foundRow, now(`${yes}. ${words}…`)]
    }
    case 'skipped':
      return [now(sentence(words))]
  }
}
