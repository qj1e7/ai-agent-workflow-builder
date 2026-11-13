import { stageOf, type NameOf } from './words'
import type { RunModel } from './runModel'

export interface Answer {
  readonly label: string
  readonly text: string
}

/**
 * What the AI troubleshooter says about a run that is no longer stopped, from the run's own events: what the agents found, then where
 * it is now. A stopped run's three answers come from the troubleshooter itself (Outcome.tsx). A run that has ended has none: the settled
 * line under its steps says the result once.
 */
export function stageAnswers(model: RunModel, found: string, nameOf: NameOf): readonly Answer[] {
  const foundRow: Answer[] = found === '' ? [] : [{ label: 'Found', text: found }]
  const yes = model.approvedBy[0]
  switch (stageOf(model)) {
    case 'stopped':
    case 'done':
    case 'declined':
      return []
    case 'retrying':
      return [{ label: 'Now', text: 'Retrying after a short wait…' }]
    case 'working':
      return [{ label: 'Now', text: 'The agents are working…' }]
    case 'waiting':
      return [...foundRow, { label: 'Now', text: 'Waiting for a yes.' }]
    case 'writing':
      return [...foundRow, { label: 'Now', text: `${yes ? `${nameOf(yes)} said yes` : 'It was approved'}. ${model.connector === 'jira' ? 'Creating the ticket…' : 'Writing the changes…'}` }]
    case 'skipped':
      return [{ label: 'Now', text: 'An earlier run is still waiting for a yes.' }]
  }
}
