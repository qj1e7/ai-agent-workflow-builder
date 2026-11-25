import { useState } from 'react'
import { ApiError } from '../../api/client'
import { useSession } from '../../api/context'
import { useRun } from '../../api/queries'
import { useNow } from '../../api/ticking'
import type { RunView } from '../../api/types'
import { Button } from '../../ui/Button'
import { useAfterPanelAction } from '../../ui/sidePanel'
import { useChat } from '../home/ChatProvider'
import { partyOf, useDecision } from './decision'
import { useLiveRun, type LiveRun } from './liveRun'
import { FixSection, useFixLeads } from './FixPanel'
import { foundLine, runByWords, tenseOf, workingLine } from './happened'
import { History } from './History'
import { DeclinedNext, StopAnswers, StopNext } from './Outcome'
import { useQuestions } from './questions'
import { POLL_FAILED_MS, useReconnectWhenBehind } from './follow'
import { RunDecision } from './RunDecision'
import { RunLine } from './RunLine'
import { RunPill } from './RunPill'
import { isFinished, type RunModel } from './runModel'
import { statusWords } from './RunPage'
import { useRunStory, type RunStory } from './useRunStory'
import { nextRunOf } from '../workflows/workflow'
import { declinedNext, declinedNowWords, feedTroubleOf, logRowsOf, messageRowsOf, RUN_PROBLEM, stageWords } from './words'
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

/**
 * A run in the side panel, in the page's shape: the workflow, who ran it and its status, then what was found, what the run wants to
 * do with the ticket as a small preview, and who decides, with Approve, Decline and Ask for an Approver. A stop keeps its three
 * answers and Retry. What happened stays folded, with the run line in it.
 */
export function RunPanel({ id }: { id: string }) {
  return <PanelFor id={id} />
}

/** A request opened from the chat: the same panel as its run, with the request in every state, for Bob and Alice alike, and its record once decided. */
export function ApprovalPanel({ id }: { id: string }) {
  return <PanelFor id={id} />
}

function PanelFor({ id }: { id: string }) {
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
  if (!ready) return <FeedNotReady connection={live.connection} onRetry={tryAgain} />
  return <RunSummary run={latest} live={live} />
}

const LOADING_APPROVAL = (
  <p className="muted" role="status">
    Loading the approval
  </p>
)

/** What the panel's request needs around it: the decision, its questions and what follows a decline. */
function useDeciding(run: RunView, story: RunStory) {
  const { me, nameOf, approval, useCase } = story
  const backToTop = useAfterPanelAction()
  const { say } = useChat()
  const party = partyOf(approval, me?.id)
  const decision = useDecision(approval, party, (recorded) => {
    backToTop?.()
    if (recorded.verdict === 'decline') say(declinedNowWords({ reason: recorded.reason ?? null }))
  })
  const questions = useQuestions(approval, nameOf, say)
  const next = declinedNext({ test: run.test, watchlist: useCase.data?.template === 'software_watchlist' }, nextRunOf(useCase.data), new Date())
  return { decision, questions, next, party }
}

/** While the agents work, and where a run stopped, the history is open, so the line shows the work or the break. */
const LIVE = new Set<RunModel['phase']['state']>(['pending', 'working', 'proposed', 'acting', 'failed'])

function RunSummary({ run, live }: { run: RunView; live: LiveRun }) {
  const story = useRunStory(run, live)
  const { me, nameOf, approval, stations, arrivedLive, useCase } = story
  const shown = story.model
  const { decision, questions, next, party } = useDeciding(run, story)
  const status = statusWords(live)
  const [fold, setFold] = useState<boolean | null>(null)
  const safeId = `${run.run_id}-safe`
  const now = useNow(() => new Date()).getTime()
  const fixAsk = {
    runId: run.run_id,
    operator: story.stopped.me?.operator === true,
    next: story.stopped.advice?.answers.next,
    offer: run.state === 'failed' ? run.fix_offer : undefined,
    now,
    approverId: me?.roles.includes('approver') ? me.id : null,
  }
  const fixLeading = useFixLeads({ ...fixAsk, fix: shown.fix })

  if (useCase.isLoading) return <Loading />
  const failure = shown.phase.state === 'failed' ? shown.phase : null
  const tense = tenseOf(shown.phase.state)
  const found = foundLine(shown.release, run.use_case_name, useCase.data?.template, new Date())
  const finished = isFinished(shown.phase)
  const main = failure ? (
    <>
      <StopAnswers failure={failure} {...story.stopped} safeId={safeId} />
      <FixSection {...fixAsk} fix={shown.fix} />
    </>
  ) : story.approvalId !== null && tense !== undefined ? (
    approval ? (
      <>
        <RunDecision
          approval={approval}
          found={found}
          tense={tense}
          decision={decision}
          facts={story.facts}
          reasons={story.quick}
          requester={nameOf(approval.requester)}
          questions={questions}
          me={me?.id}
          party={party}
          nameOf={nameOf}
          next={null}
          now={new Date()}
        />
        {shown.phase.state === 'rejected' && next ? <DeclinedNext words={next} testAgain={testAgainOf({ ...run, state: shown.phase.state }, me, story.stopped.modelOff ?? false)} /> : null}
      </>
    ) : (
      LOADING_APPROVAL
    )
  ) : (
    <>
      {found ? <p>{found}</p> : null}
      <p>{finished ? stageWords(story.facts, nameOf) : workingLine(story.facts)}</p>
    </>
  )
  return (
    <div className={styles['panelView']}>
      <div className={styles['head']}>
        <p className={styles['kind']}>
          {run.use_case_name} · {runByWords(shown.trigger, shown.startedBy, nameOf)}
        </p>
        <RunPill facts={story.facts} nameOf={nameOf} />
      </div>
      {status ? (
        <p className="muted" role="status">
          {status}
        </p>
      ) : null}
      {main}
      <History
        rows={logRowsOf(shown.chat, nameOf, story.quick)}
        messages={messageRowsOf(shown.chat)}
        loadedUpTo={live.loadedUpTo}
        open={fold ?? LIVE.has(shown.phase.state)}
        onToggle={setFold}
        line={<RunLine stations={stations} arrivedLive={arrivedLive} settled={null} small />}
      />
      {failure ? (
        <div className={styles['panelFoot']}>
          <StopNext runId={run.run_id} failure={failure} {...story.stopped} quiet={fixLeading} safeId={safeId} />
        </div>
      ) : null}
    </div>
  )
}

