import type { UseCaseView } from '../../api/types'
import { faceId } from '../agents/agents'
import { emptyModel, stationsOf, type PlanBlock, type Station } from '../run/runModel'
import { scheduleShort } from '../run/words'
import { cardsOf } from './workflow'

/** What each kind of step can touch, in a few words under it. A step that writes says it waits for a yes. */
const TAGS: Record<Station['spot']['at'], string> = {
  started: 'No system access',
  planner: 'No system access',
  agent: 'Reads only',
  gate: 'Waits for a yes',
  write: 'Writes after a yes',
  done: 'No system access',
}

/**
 * The run line for a workflow that is not running: the same steps a run draws, none reached yet, with the agents' faces above their steps and a tag under each.
 * The page draws it with the run line's large variant, so the workflow and its runs read as one picture.
 */
export function templateLine(useCase: Pick<UseCaseView, 'schedule' | 'plan' | 'agents' | 'template'>): Station[] {
  const plan: PlanBlock[] = useCase.plan.map((block) => ({ key: block.key, name: block.name, kind: block.kind }))
  const agents = cardsOf(useCase).map((card) => ({ id: faceId(card), display: card.name }))
  const trigger = useCase.schedule ? scheduleShort(useCase.schedule) : 'Run now'
  const model = { ...emptyModel, trigger: useCase.schedule ? ('schedule' as const) : emptyModel.trigger, agents }
  return stationsOf(model, plan, trigger).map((station) => ({
    ...station,
    state: 'todo',
    face: 'idle',
    under: { kind: 'note', text: TAGS[station.spot.at] },
  }))
}
