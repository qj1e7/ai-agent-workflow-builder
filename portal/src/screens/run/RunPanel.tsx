import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { useRun } from '../../api/queries'
import type { ApprovalView, RunView } from '../../api/types'
import { Button } from '../../ui/Button'
import { useAfterPanelAction } from '../../ui/sidePanel'
import { useChat } from '../home/ChatProvider'
import { ApprovalGate, NotChecked } from './ApprovalGate'
import { openStep, partyOf, useDecision, useNotChecked } from './decision'
import { useLiveRun, type LiveRun } from './liveRun'
import { AnswerList, DeclinedNext, StopAnswers, StopNext } from './Outcome'
import { QuestionThread } from './QuestionThread'
import { useQuestions } from './questions'
import { POLL_FAILED_MS, useReconnectWhenBehind } from './follow'
import { declinedSoFarWords, statusWords } from './RunPage'
import { RunLine } from './RunLine'
import { RunPill } from './RunPill'
import { useRunStory, type RunStory } from './useRunStory'
import { nextRunOf } from '../workflows/workflow'
import { declinedNext, declinedNowWords, feedTroubleOf, RUN_PROBLEM } from './words'
import { testAgainOf } from './testAgain'
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

type Shows = 'run' | 'approval'

/**
 * A run in the side panel (spec 3.3): its state, its headline and the run line, with a stop's three answers and Retry. A finished
 * run keeps its line with the settled line under it, as the sketch's panel does. Only the chat's card folds. While it waits for a
 * yes the reader may give, it is the approval instead. Someone who can't decide sees the summary, as in the prototype.
 */
export function RunPanel({ id }: { id: string }) {
  return <PanelFor id={id} shows="run" />
}

/** A request opened from the chat (the sketch's approval panel): the approval in every state, for Bob and Alice alike, with its record once decided. */
export function ApprovalPanel({ id }: { id: string }) {
  return <PanelFor id={id} shows="approval" />
}

function PanelFor({ id, shows }: { id: string; shows: Shows }) {
  const run = useRun(id)
  if (run.isError) {
    const gone = run.error instanceof ApiError && run.error.status === 404
    return gone ? <p className="muted">That run isn’t here any more.</p> : <Problem onRetry={() => void run.refetch()} />
  }
  if (!run.data) return <Loading />
  return <LiveRunPanel run={run.data} shows={shows} />
}

function LiveRunPanel({ run, shows }: { run: RunView; shows: Shows }) {
  const { live, restart, tryAgain } = useLiveRun(run.run_id)
  const failed = live.head.phase.state === 'failed'
  const latest = useRun(run.run_id, { poll: failed ? POLL_FAILED_MS : false }).data ?? run
  useReconnectWhenBehind(failed && live.loaded && latest.last_seq > live.head.seq, restart)
  const ready = live.loaded || live.connection.is === 'live' || live.connection.is === 'settled'
  if (!ready) return <FeedNotReady connection={live.connection} onRetry={tryAgain} />
  return shows === 'approval' ? <ApprovalSummary run={latest} live={live} /> : <RunSummary run={latest} live={live} />
}

const LOADING_WRITES = (
  <p className="muted" role="status">
    Loading what will be written
  </p>
)

/** What the panel's request needs around it: the decision, its questions, what wasn't checked and what follows a decline. */
function useRequest(run: RunView, story: RunStory) {
  const { me, nameOf, approval, useCase } = story
  const backToTop = useAfterPanelAction()
  const { say } = useChat()
  const party = partyOf(approval, me?.id)
  const decision = useDecision(approval, party, (recorded) => {
    backToTop?.()
    if (recorded.verdict === 'decline') say(declinedNowWords({ reason: recorded.reason ?? null }))
  })
  const questions = useQuestions(approval, nameOf, say)
  const notChecked = useNotChecked(approval, useCase.data)
  const next = declinedNext({ test: run.test, watchlist: useCase.data?.template === 'software_watchlist' }, nextRunOf(useCase.data), new Date())
  const gate = (shown: ApprovalView, checked: readonly string[]) => (
    <ApprovalGate
      approval={shown}
      page={null}
      decision={decision}
      facts={story.facts}
      notChecked={checked}
      reasons={story.quick}
      requester={nameOf(shown.requester)}
      questions={questions}
      me={me?.id}
      party={party}
      nameOf={nameOf}
      next={next}
      now={new Date()}
    />
  )
  return { decision, questions, notChecked, next, gate }
}

function ApprovalSummary({ run, live }: { run: RunView; live: LiveRun }) {
  const story = useRunStory(run, live)
  const { notChecked, gate } = useRequest(run, story)
  if (story.useCase.isLoading) return <Loading />
  if (story.approvalId === null) return <RunSummary run={run} live={live} />
  if (!story.approval || notChecked === null) return LOADING_WRITES
  return gate(story.approval, notChecked)
}

function RunSummary({ run, live }: { run: RunView; live: LiveRun }) {
  const story = useRunStory(run, live)
  const { me, nameOf, approval, stations, settled, arrivedLive, useCase } = story
  const waiting = story.model.phase.state === 'awaiting_approval'
  const { decision, questions, notChecked, next, gate } = useRequest(run, story)
  const status = statusWords(decision, live)
  const declinedSoFar = declinedSoFarWords(decision, live, nameOf)
  const safeId = `${run.run_id}-safe`

  if (useCase.isLoading) return <Loading />
  if (waiting && story.approvalId !== null && (!approval || notChecked === null)) return LOADING_WRITES
  if (waiting && approval?.you_can_decide && openStep(approval) && decision.recorded === null) return gate(approval, notChecked ?? [])
  const failure = story.model.phase.state === 'failed' ? story.model.phase : null
  return (
    <div className={styles['panelView']}>
      <div className={styles['head']}>
        <p className={styles['kind']}>{story.kind}</p>
        <RunPill facts={story.facts} />
      </div>
      {status ? (
        <p className="muted" role="status">
          {status}
        </p>
      ) : null}
      {declinedSoFar ? <p className="muted">{declinedSoFar}</p> : null}
      <RunLine stations={stations} arrivedLive={arrivedLive} settled={settled} small />
      {story.model.phase.state === 'rejected' && next ? <DeclinedNext words={next} testAgain={testAgainOf({ ...run, state: story.model.phase.state }, me, story.stopped.modelOff ?? false)} /> : null}
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
          {openStep(approval) === null ? <NotChecked lines={notChecked ?? []} level={3} /> : null}
          <QuestionThread approval={approval} me={me?.id} nameOf={nameOf} answer={questions.answer} />
        </>
      ) : null}
    </div>
  )
}
