import type { RunModel } from './runModel'

const WORKING = new Set<RunModel['phase']['state']>(['pending', 'working', 'proposed', 'acting'])

/** Run history is open while the agents work, and folded once the run needs the person or is over, a stopped run included: the troubleshooter's answers say what happened. */
export function historyOpen(choice: boolean | null, model: RunModel): boolean {
  return choice ?? WORKING.has(model.phase.state)
}
