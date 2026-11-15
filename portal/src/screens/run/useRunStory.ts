import { displayName, usePeople } from '../../api/people'
import { useApproval, useMe, useModelOff, useTroubleshoot, useUseCase } from '../../api/queries'
import { isOperator } from '../../api/me'
import type { ApprovalView, Me, RunView, UseCaseView } from '../../api/types'
import { declineReasons, foundOf } from './decision'
import type { LiveRun } from './liveRun'
import { stationsOf, type PlanBlock, type RunModel, type Station } from './runModel'
import { stageAnswers, type Answer } from './stageAnswers'
import { runKind, settledOf, stageFactsOf, triggerWords, type NameOf, type Settled, type StageFacts } from './words'
import type { TroubleshootingProps } from './Outcome'

export function approvalIdOf(run: RunView, model: RunModel): string | null {
  if (model.approvalId) return model.approvalId
  return 'approval' in run ? run.approval.approval_id : null
}

export function useNameOf(model: RunModel): NameOf {
  const people = usePeople()
  return (id) => model.people[id] ?? displayName(people, id)
}

export function planOf(useCase: UseCaseView | undefined): PlanBlock[] | null {
  return useCase ? useCase.plan.map((block) => ({ key: block.key, name: block.name, kind: block.kind })) : null
}

export interface RunStory {
  readonly model: RunModel
  readonly me: Me | undefined
  readonly nameOf: NameOf
  readonly useCase: { readonly data: UseCaseView | undefined; readonly isLoading: boolean }
  readonly approvalId: string | null
  readonly approval: ApprovalView | undefined
  /** Where the run stands, for its pill and every word about its state. */
  readonly facts: StageFacts
  readonly stations: readonly Station[]
  readonly settled: Settled | null
  readonly arrivedLive: string | null
  readonly found: string
  readonly quick: readonly string[]
  /** The rows beside the troubleshooter's face while the run is not stopped. */
  readonly answers: readonly Answer[]
  readonly stopped: Pick<TroubleshootingProps, 'advice' | 'loading' | 'me' | 'reports' | 'nameOf' | 'modelOff'>
  readonly kind: string
}

export interface StoryInputs {
  readonly run: Pick<RunView, 'run_id' | 'started_at'>
  readonly live: Pick<LiveRun, 'shown' | 'head' | 'loadedUpTo'>
  readonly me: Me | undefined
  readonly nameOf: NameOf
  readonly useCase: UseCaseView | undefined
  readonly approval: ApprovalView | undefined
  readonly advice: TroubleshootingProps['advice']
  readonly adviceLoading: boolean
  readonly modelOff: boolean
  readonly now: Date
}

/** The run's story from what was read: the pure part of useRunStory, so a card can be drawn from fixture events. */
export function storyOf({ run, live, me, nameOf, useCase, approval, advice, adviceLoading, modelOff, now }: StoryInputs): Omit<RunStory, 'useCase' | 'approvalId'> {
  const { shown, head, loadedUpTo } = live
  const quick = declineReasons(useCase?.template)
  const stations = stationsOf(shown, planOf(useCase), triggerWords(shown, useCase?.schedule ?? null, nameOf, run.started_at))
  const found = foundOf(head.found, approval?.found)
  return {
    model: shown,
    me,
    nameOf,
    approval,
    facts: stageFactsOf(shown),
    stations,
    settled: settledOf(shown, nameOf, now, quick),
    arrivedLive: shown.spotSeq > loadedUpTo ? (stations.findLast((station) => station.state !== 'todo')?.key ?? null) : null,
    found,
    quick,
    answers: stageAnswers(shown, found, nameOf),
    stopped: {
      advice,
      loading: adviceLoading,
      me: me ? { id: me.id, name: me.display, operator: isOperator(me) } : undefined,
      reports: shown.reports,
      nameOf,
      modelOff,
    },
    kind: runKind(run.started_at, now),
  }
}

/**
 * Everything the card, the panel and the page say about one run, read once from the run's own events and its workflow, so the
 * three never disagree (principle 7). The stage is the run's state in the words every screen shares.
 */
export function useRunStory(run: RunView, live: LiveRun): RunStory {
  const me = useMe().data
  const modelOff = useModelOff()
  const nameOf = useNameOf(live.head)
  const useCase = useUseCase(run.use_case_id)
  const approvalId = approvalIdOf(run, live.head)
  const waiting = live.shown.phase.state === 'awaiting_approval'
  const approval = useApproval(approvalId ?? '', { poll: waiting, enabled: approvalId !== null })
  const attempt = live.head.chat.filter((item) => item.kind === 'retried').length
  const troubleshoot = useTroubleshoot(run.run_id, live.shown.phase.state === 'failed' && live.head.phase.state === 'failed', attempt)
  const story = storyOf({ run, live, me, nameOf, useCase: useCase.data, approval: approval.data, advice: troubleshoot.data, adviceLoading: troubleshoot.isPending, modelOff, now: new Date() })
  return { ...story, useCase, approvalId }
}
