import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { isOperator } from '../../api/me'
import { useApproval, useMe, useModelOff, useRun, useTroubleshoot, useUseCase } from '../../api/queries'
import type { RunView } from '../../api/types'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { useAfterPanelAction, type PanelViewProps } from '../../ui/sidePanel'
import { ApprovalGate } from './ApprovalGate'
import { openStep, partyOf, useDecision } from './decision'
import { useLiveRun, type LiveRun } from './liveRun'
import { Troubleshooting } from './Outcome'
import { approvalIdOf, planOf, POLL_FAILED_MS, statusWords, useNameOf, useReconnectWhenBehind } from './RunPage'
import { RunLine } from './RunLine'
import { reachOf, stationsOf } from './runModel'
import { feedTroubleOf, headlineOf, RUN_PROBLEM, shortTime, writeLabel } from './words'
import styles from './RunPage.module.css'

const RUN = 'Run'

function Loading() {
  return (
    <p className="muted" role="status">
      Loading the run
    </p>
  )
}

function Problem({ onRetry }: { onRetry: () => void }) {
  return (
    <p role="alert">
      {RUN_PROBLEM.heading}. <Button onClick={onRetry}>Try again</Button>
    </p>
  )
}

function FeedNotReady({ connection, onRetry }: { connection: LiveRun['connection']; onRetry: () => void }) {
  const { kind } = useSession()
  const trouble = feedTroubleOf(connection, kind)
  switch (trouble.kind) {
    case 'loading':
      return <Loading />
    case 'waiting':
      return (
        <p className="muted" role="status">
          {trouble.words}
        </p>
      )
    case 'stop':
      return <p>{trouble.lead}</p>
    case 'retry':
      return <Problem onRetry={onRetry} />
  }
}

/**
 * A run in the side panel (spec 3.3): its state, its headline and the run line, with a stop's three answers and Retry. While
 * it waits for a yes the reader may give, it is the approval instead, from the run page's own gate (spec 10.4).
 */
export function RunPanel({ id, children }: PanelViewProps) {
  const run = useRun(id)
  if (run.isError) {
    const gone = run.error instanceof ApiError && run.error.status === 404
    return children({ title: RUN, page: null, body: gone ? <p className="muted">That run isn’t here any more.</p> : <Problem onRetry={() => void run.refetch()} /> })
  }
  if (!run.data) return children({ title: RUN, page: null, body: <Loading /> })
  return <LiveRunPanel run={run.data}>{children}</LiveRunPanel>
}

function LiveRunPanel({ run, children }: { run: RunView; children: PanelViewProps['children'] }) {
  const { live, restart, tryAgain } = useLiveRun(run.run_id)
  const failed = live.head.phase.state === 'failed'
  const latest = useRun(run.run_id, { poll: failed ? POLL_FAILED_MS : false }).data ?? run
  useReconnectWhenBehind(failed && live.loaded && latest.last_seq > live.head.seq, restart)
  const ready = live.loaded || live.connection.is === 'live' || live.connection.is === 'settled'
  return children({
    title: run.use_case_name,
    page: `/runs/${run.run_id}`,
    body: ready ? <RunSummary run={latest} live={live} /> : <FeedNotReady connection={live.connection} onRetry={tryAgain} />,
  })
}

function RunSummary({ run, live }: { run: RunView; live: LiveRun }) {
  const { shown, head } = live
  const me = useMe().data
  const nameOf = useNameOf(head)
  const modelOff = useModelOff()
  const backToTop = useAfterPanelAction()
  const useCase = useUseCase(run.use_case_id)
  const approvalId = approvalIdOf(run, head)
  const waiting = shown.phase.state === 'awaiting_approval'
  const approval = useApproval(approvalId ?? '', { poll: waiting, enabled: approvalId !== null && (waiting || head.phase.state === 'awaiting_approval') })
  const attempt = head.chat.filter((item) => item.kind === 'retried').length
  const troubleshoot = useTroubleshoot(run.run_id, shown.phase.state === 'failed' && head.phase.state === 'failed', attempt)
  const decision = useDecision(approval.data, partyOf(approval.data, me?.id), () => backToTop?.())

  const stations = stationsOf(shown, planOf(useCase.data), writeLabel)
  const headline = headlineOf(shown, stations, approval.data && waiting ? approval.data.actions : null)
  const status = statusWords(decision.recorded, live)

  if (waiting && approval.data?.you_can_decide && openStep(approval.data) && decision.recorded === null) {
    return <ApprovalGate approval={approval.data} page={null} decision={decision} />
  }
  return (
    <>
      <div>
        <span className={cx(styles['pill'], styles[headline.pill.tone])}>{headline.pill.label}</span>
      </div>
      <p>{headline.text}</p>
      {status ? (
        <p className="muted" role="status">
          {status}
        </p>
      ) : null}
      <RunLine stations={stations} reach={reachOf(stations)} arrivedLive={null} startedAt={shortTime(run.started_at)} nameOf={nameOf} />
      {shown.phase.state === 'failed' ? (
        <Troubleshooting
          runId={run.run_id}
          failure={shown.phase}
          advice={troubleshoot.data}
          loading={troubleshoot.isPending}
          me={me ? { id: me.id, name: me.display, operator: isOperator(me) } : undefined}
          reports={shown.reports}
          nameOf={nameOf}
          modelOff={modelOff}
        />
      ) : null}
    </>
  )
}
