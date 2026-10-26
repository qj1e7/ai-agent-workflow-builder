import { QUESTS, type Quest, type StepDone, type TourStep } from './quests'

export const TOUR_KEY = 'portal.tour'

export interface TourState {
  readonly open: boolean
  readonly folded: boolean
  /** Which quest. The number of quests means the whole tour is finished. */
  readonly quest: number
  /** Which step of the quest. The quest's step count means the quest is finished and the next one waits. */
  readonly step: number
  /** Steps the person did, so the checklist ticks them. A skipped step stays unticked. */
  readonly ticked: readonly string[]
}

export const FRESH: TourState = { open: false, folded: false, quest: 0, step: 0, ticked: [] }

export type TourAction =
  | { readonly type: 'open' }
  | { readonly type: 'close' }
  | { readonly type: 'fold'; readonly folded: boolean }
  | { readonly type: 'done'; readonly id: string }
  | { readonly type: 'skip' }
  | { readonly type: 'back' }
  | { readonly type: 'next_quest' }
  | { readonly type: 'restart' }

export type Place =
  | { readonly is: 'step'; readonly quest: Quest; readonly step: TourStep }
  | { readonly is: 'quest_done'; readonly quest: Quest }
  | { readonly is: 'tour_done' }

export function placeOf(state: TourState, quests: readonly Quest[] = QUESTS): Place {
  const quest = quests[state.quest]
  if (!quest) return { is: 'tour_done' }
  const step = quest.steps[state.step]
  return step ? { is: 'step', quest, step } : { is: 'quest_done', quest }
}

export function tourStep(state: TourState, action: TourAction, quests: readonly Quest[] = QUESTS): TourState {
  const place = placeOf(state, quests)
  switch (action.type) {
    case 'open':
      return place.is === 'tour_done' ? { ...FRESH, open: true } : { ...state, open: true, folded: false }
    case 'close':
      return { ...state, open: false }
    case 'fold':
      return { ...state, folded: action.folded }
    case 'done':
      if (place.is !== 'step' || place.step.id !== action.id) return state
      return { ...state, step: state.step + 1, ticked: state.ticked.includes(action.id) ? state.ticked : [...state.ticked, action.id] }
    case 'skip':
      return place.is === 'step' ? { ...state, step: state.step + 1 } : state
    case 'back': {
      if (state.step > 0 && place.is !== 'tour_done') return { ...state, step: state.step - 1 }
      const previous = quests[state.quest - 1]
      return previous ? { ...state, quest: state.quest - 1, step: previous.steps.length - 1 } : state
    }
    case 'next_quest':
      return place.is === 'quest_done' ? { ...state, quest: state.quest + 1, step: 0 } : state
    case 'restart':
      return { ...FRESH, open: true }
  }
}

/** Reads what localStorage kept. Anything unexpected, or a place that no longer exists, starts the tour fresh. */
export function parseTour(raw: string | null, quests: readonly Quest[] = QUESTS): TourState {
  if (raw === null) return FRESH
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return FRESH
  }
  if (typeof value !== 'object' || value === null) return FRESH
  const kept = value as Record<string, unknown>
  const quest = kept['quest']
  const step = kept['step']
  if (!Number.isInteger(quest) || !Number.isInteger(step)) return FRESH
  const questAt = quest as number
  const stepAt = step as number
  const steps = quests[questAt]?.steps.length ?? 0
  const fits = questAt >= 0 && stepAt >= 0 && (questAt < quests.length ? stepAt <= steps : questAt === quests.length && stepAt === 0)
  if (!fits) return FRESH
  const ticked = Array.isArray(kept['ticked']) ? kept['ticked'].filter((id): id is string => typeof id === 'string') : []
  return { open: kept['open'] === true, folded: kept['folded'] === true, quest: questAt, step: stepAt, ticked }
}

/** With real sign-in there is no user menu, so a step that switches users only explains, and the person presses Next. */
export function shownStep(step: TourStep, canSwitchUser: boolean): TourStep {
  if (canSwitchUser || step.signedIn === undefined) return step
  return { id: step.id, label: step.label, say: step.signedIn, done: { kind: 'read' } }
}

/** '/runs/*' matches any one run's page. Any other pattern matches only that page. */
export function pathMatches(pattern: string, pathname: string): boolean {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  if (pattern.endsWith('/*')) {
    const prefix = pattern.slice(0, -1)
    return path.startsWith(prefix) && path.length > prefix.length
  }
  return path === pattern
}

export interface Who {
  readonly id: string
  readonly roles: readonly string[]
}

/** Whether a step that waits for a page or a person is already met. Steps that wait for a press or a sight are watched in the page. */
export function alreadyMet(done: StepDone, pathname: string, who: Who | null): boolean {
  switch (done.kind) {
    case 'page':
      return pathMatches(done.at, pathname)
    case 'user':
      return who?.id === done.id
    case 'role':
      return who?.roles.includes(done.role) ?? false
    default:
      return false
  }
}

export function stepCount(quests: readonly Quest[] = QUESTS): number {
  return quests.reduce((sum, quest) => sum + quest.steps.length, 0)
}
