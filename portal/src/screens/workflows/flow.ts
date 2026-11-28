import type { UseCaseView } from '../../api/types'
import type { StepIcon, StepState } from '../../ui/StepLine'
import { emptyModel, foldWire, stationsOf, type AgentRef, type PlanBlock } from '../run/runModel'
import { stageFactsOf, stageWords, type StageFacts } from '../run/words'
import { templateLine } from './line'
import { lineWhen } from './times'

/** A run as the page has read it: its events, from the endpoint the run page uses. */
export interface FlowRun {
  readonly runId: string
  readonly events: readonly unknown[]
  readonly startedAt: string
  /** Where the run stands, as the runs list says it, with why it stopped. When absent, the events say it. */
  readonly stage?: StageFacts
}

export interface FlowStep {
  readonly key: string
  readonly label: string
  readonly icon: StepIcon
  readonly agent: AgentRef | null
  /** What the step can touch, in a few words. */
  readonly tag: string
  /** Where the latest run left the step. Null when no run is drawn: nothing is guessed. */
  readonly state: StepState | null
}

export interface FlowNote {
  readonly key: string
  readonly tone: 'err' | 'wait'
  readonly text: string
}

export interface Flow {
  readonly steps: readonly FlowStep[]
  readonly note: FlowNote | null
  /** "with today’s 8:00 run", after the heading. Null when no run is drawn. */
  readonly ranWhen: string | null
}

/** The key's order, as the sketch lists it. */
const KEY_ORDER: readonly StepState[] = ['done', 'now', 'wait', 'err', 'no', 'skip', 'todo']

/** The states on the boxes, in the key's order. Nothing is listed when no run is drawn. */
export function flowKeyOf(flow: Flow): StepState[] {
  const has = new Set(flow.steps.map((step) => step.state))
  return KEY_ORDER.filter((state) => has.has(state))
}

/** The heading's time, in the sketch's words: "with today’s 8:00 run", or "with the Tue 3 Nov run" for an earlier day. */
export function ranWords(startedAt: string, now: Date): string {
  const when = lineWhen(startedAt, now)
  return when.startsWith('Today ') ? `with today’s ${when.slice('Today '.length)} run` : `with the ${when} run`
}

/**
 * The workflow's designed steps, coloured by the latest run when there is one. Names, tags and agents come from the workflow, the
 * states from the run's events, folded as the run page folds them. A step the run did not reach reads as not reached, and one it skipped as skipped. A run with no events draws no state: nothing is guessed.
 */
export function flowOf(useCase: Pick<UseCaseView, 'schedule' | 'plan' | 'agents' | 'template'>, run: FlowRun | null, now: Date): Flow {
  const designed = templateLine(useCase)
  const tagOf = (station: (typeof designed)[number]) => (station.under?.kind === 'note' ? station.under.text : '')
  if (run === null || run.events.length === 0) {
    return { steps: designed.map((station) => ({ key: station.key, label: station.label, icon: station.icon, agent: station.agent, tag: tagOf(station), state: null })), note: null, ranWhen: null }
  }
  const plan: PlanBlock[] = useCase.plan.map((block) => ({ key: block.key, name: block.name, kind: block.kind }))
  const model = foldWire(emptyModel, run.events, run.runId)
  const reached = new Map(stationsOf(model, plan, '').map((station) => [station.key, station.state]))
  const steps = designed.map(
    (station): FlowStep => {
      const state = reached.get(station.key) ?? 'todo'
      return { key: station.key, label: station.label, icon: station.icon, agent: station.agent, tag: tagOf(station), state }
    },
  )
  const at = steps.find((step) => step.state === 'err' || step.state === 'wait')
  const note: FlowNote | null = at ? { key: at.key, tone: at.state === 'err' ? 'err' : 'wait', text: stageWords(run.stage ?? stageFactsOf(model), (id) => id) } : null
  return { steps, note, ranWhen: ranWords(run.startedAt, now) }
}
