import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { useRun } from '../../api/queries'
import type { RunView } from '../../api/types'
import { Button } from '../../ui/Button'
import { useAfterPanelAction } from '../../ui/sidePanel'
import { useChat } from '../home/ChatProvider'
import { ApprovalGate, NotChecked } from './ApprovalGate'
import { openStep, partyOf, useDecision, useNotChecked } from './decision'
import { useLiveRun, type LiveRun } from './liveRun'
import { AnswerList, StopAnswers, StopNext } from './Outcome'
import { QuestionThread } from './QuestionThread'
import { useQuestions } from './questions'
import { POLL_FAILED_MS, useReconnectWhenBehind } from './follow'
import { declinedSoFarWords, statusWords } from './RunPage'
import { RunLine } from './RunLine'
import { RunPill } from './RunPill'
import { useRunStory } from './useRunStory'
import { nextRunOf } from '../workflows/workflow'
import { declinedNext, declinedNowWords, feedTroubleOf, RUN_PROBLEM } from './words'
import styles from './RunPage.module.css'

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
 * A run in the side panel (spec 3.3): its state, its headline and the run line, with a stop's three answers and Retry. A finished
 * run keeps its line with the settled line under it, as the sketch's panel does. Only the chat's card folds. While it waits for a
 * yes the reader may give, it is the approval instead, from the run page's own gate (spec 10.4). Someone who can't decide sees the
 * summary, as in the prototype.
 */
export function RunPanel({ id }: { id: string }) {
  const run = useRun(id)
  if (run.isError) {
    const gone = run.error instanceof ApiError && run.error.status === 404
    return gone ? <p className="muted">That run isn’t here any more.</p> : <Problem onRetry={() => void run.refetch()} />
  }
  if (!run.data) return <Loading />
  return <LiveRunPanel run={run.data} />
}

function LiveRunPanel({ run }: { run: RunView }) {
  const { live, restart, tryAgain } = useLiveRun(run.run_id)
  const failed = live.head.phase.state === 'failed'
  const latest = useRun(run.run_id, { poll: failed ? POLL_FAILED_MS : false }).data ?? run
  useReconnectWhenBehind(failed && live.loaded && latest.last_seq > live.head.seq, restart)
  const ready = live.loaded || live.connection.is === 'live' || live.connection.is === 'settled'
  return ready ? <RunSummary run={latest} live={live} /> : <FeedNotReady connection={live.connection} onRetry={tryAgain} />
}

function RunSummary({ run, live }: { run: RunView; live: LiveRun }) {
  const story = useRunStory(run, live)
  const { me, nameOf, approval, stations, settled, headline, arrivedLive, useCase } = story
  const backToTop = useAfterPanelAction()
  const waiting = story.model.phase.state === 'awaiting_approval'
  const { say } = useChat()
  const decision = useDecision(approval, partyOf(approval, me?.id), (recorded) => {
    backToTop?.()
    if (recorded.verdict === 'decline') say(declinedNowWords({ reason: recorded.reason ?? null }))
  })
  const questions = useQuestions(approval, nameOf, say)
  const notChecked = useNotChecked(approval, useCase.data)
  const status = statusWords(decision, live)
  const declinedSoFar = declinedSoFarWords(decision, live, nameOf)
  const safeId = `${run.run_id}-safe`
  const next = declinedNext({ test: run.test, watchlist: useCase.data?.template === 'software_watchlist' }, nextRunOf(useCase.data), new Date())

  if (useCase.isLoading) return <Loading />
  if (waiting && story.approvalId !== null && (!approval || notChecked === null)) {
    return (
      <p className="muted" role="status">
        Loading what will be written
      </p>
    )
  }
  if (waiting && approval?.you_can_decide && openStep(approval) && decision.recorded === null) {
    return (
      <ApprovalGate
        approval={approval}
        page={null}
        decision={decision}
        notChecked={notChecked ?? []}
        reasons={story.quick}
        requester={nameOf(approval.requester)}
        questions={questions}
        me={me?.id}
        nameOf={nameOf}
      />
    )
  }
  const failure = story.model.phase.state === 'failed' ? story.model.phase : null
  return (
    <div className={styles['panelView']}>
      <div className={styles['head']}>
        <p className={styles['kind']}>{story.kind}</p>
        <RunPill pill={headline.pill} />
      </div>
      {status ? (
        <p className="muted" role="status">
          {status}
        </p>
      ) : null}
      {declinedSoFar ? <p className="muted">{declinedSoFar}</p> : null}
      <RunLine stations={stations} arrivedLive={arrivedLive} settled={settled} small />
      {story.model.phase.state === 'rejected' && next ? <p>{next}</p> : null}
      {failure ? (
        <>
          <StopAnswers failure={failure} {...story.stopped} safeId={safeId} />
          <div className={styles['panelFoot']}>
            <StopNext runId={run.run_id} failure={failure} {...story.stopped} safeId={safeId} />
          </div>
        </>
      ) : story.answers.length > 0 && !waiting ? (
        <AnswerList answers={story.answers} />
      ) : null}
      {approval && !failure ? (
        <>
          {openStep(approval) === null ? <NotChecked lines={notChecked ?? []} /> : null}
          <QuestionThread approval={approval} me={me?.id} nameOf={nameOf} answer={questions.answer} />
        </>
      ) : null}
    </div>
  )
}
