import { andList, stageFactsOf, stageOf, stageWords, type NameOf } from './words'
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
  const stage = stageOf(model)
  const words = stageWords(stage, stageFactsOf(model))
  const now = (text: string): Answer => ({ label: 'Now', text })
  switch (stage) {
    case 'stopped':
    case 'done':
    case 'declined':
      return []
    case 'retrying':
      return [now(`${words} after a short wait…`)]
    case 'working':
      return [now(`${words}…`)]
    case 'waiting':
      return [...foundRow, now(`${words}.`)]
    case 'writing': {
      const yes = model.approvedBy.length > 0 ? `${andList(model.approvedBy.map(nameOf))} said yes` : 'It was approved'
      return [...foundRow, now(`${yes}. ${words}…`)]
    }
    case 'skipped':
      return [now(`${words}.`)]
  }
}
