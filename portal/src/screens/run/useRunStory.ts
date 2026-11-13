import { displayName, usePeople } from '../../api/people'
import { useApproval, useMe, useModelOff, useTroubleshoot, useUseCase } from '../../api/queries'
import { isOperator } from '../../api/me'
import type { ApprovalView, Me, RunView, UseCaseView } from '../../api/types'
import { declineReasons, foundOf } from './decision'
import type { LiveRun } from './liveRun'
import { stationsOf, type PlanBlock, type RunModel, type Station } from './runModel'
import { stageAnswers, type Answer } from './stageAnswers'
import { headlineOf, runKind, settledOf, stageOf, triggerWords, type Headline, type NameOf, type RunStage, type Settled } from './words'
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
  readonly stage: RunStage
  readonly stations: readonly Station[]
  readonly settled: Settled | null
  readonly headline: Headline
  readonly arrivedLive: string | null
  readonly found: string
  readonly quick: readonly string[]
  /** The rows beside the troubleshooter's face while the run is not stopped. */
  readonly answers: readonly Answer[]
  readonly stopped: Pick<TroubleshootingProps, 'advice' | 'loading' | 'me' | 'reports' | 'nameOf' | 'modelOff'>
  readonly kind: string
}

/**
 * Everything the card, the panel and the page say about one run, read once from the run's own events and its workflow, so the
 * three never disagree (principle 7). The stage is the run's state in the words every screen shares.
 */
export function useRunStory(run: RunView, live: LiveRun): RunStory {
  const { shown, head, loadedUpTo } = live
  const me = useMe().data
  const modelOff = useModelOff()
  const nameOf = useNameOf(head)
  const useCase = useUseCase(run.use_case_id)
  const approvalId = approvalIdOf(run, head)
  const waiting = shown.phase.state === 'awaiting_approval'
  const approval = useApproval(approvalId ?? '', { poll: waiting, enabled: approvalId !== null })
  const attempt = head.chat.filter((item) => item.kind === 'retried').length
  const troubleshoot = useTroubleshoot(run.run_id, shown.phase.state === 'failed' && head.phase.state === 'failed', attempt)
  const quick = declineReasons(useCase.data?.template)
  const plan: PlanBlock[] | null = planOf(useCase.data)
  const stations = stationsOf(shown, plan, triggerWords(shown, useCase.data?.schedule ?? null, nameOf, run.started_at))
  const settled = settledOf(shown, nameOf, new Date(), quick)
  const headline = headlineOf(shown, stations, approval.data && waiting ? approval.data.actions : null)
  const found = foundOf(head.found, approval.data?.found)
  return {
    model: shown,
    me,
    nameOf,
    useCase,
    approvalId,
    approval: approval.data,
    stage: stageOf(shown),
    stations,
    settled,
    headline,
    arrivedLive: shown.spotSeq > loadedUpTo ? (stations.findLast((station) => station.state !== 'todo')?.key ?? null) : null,
    found,
    quick,
    answers: stageAnswers(shown, found, nameOf),
    stopped: {
      advice: troubleshoot.data,
      loading: troubleshoot.isPending,
      me: me ? { id: me.id, name: me.display, operator: isOperator(me) } : undefined,
      reports: shown.reports,
      nameOf,
      modelOff,
    },
    kind: runKind(run.started_at, new Date()),
  }
}
