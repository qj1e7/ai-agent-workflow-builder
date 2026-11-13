import { useEffect, useState, type ReactNode } from 'react'
import { useHome } from '../../api/homeQueries'
import { useRun, useMe, useUseCases } from '../../api/queries'
import { isOperator } from '../../api/me'
import type { HomeOut, RunView, UseCaseView } from '../../api/types'
import { AgentFace } from '../../ui/AgentFace'
import { ButtonLink } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { OpenButton } from '../../ui/OpenItem'
import { useShownInPanel } from '../../ui/sidePanel'
import { AnswerList, StopAnswers, StopNext } from '../run/Outcome'
import { RunLine, SettledLine } from '../run/RunLine'
import { RunPill } from '../run/RunPill'
import { useLiveRun } from '../run/liveRun'
import { TROUBLE_FACE } from '../run/troubleFace'
import { type RunStory, useRunStory } from '../run/useRunStory'
import { stageWords, type RunStage } from '../run/words'
import styles from './Planner.module.css'

type Say = (text: string) => void

interface Stop {
  readonly run_id: string
  readonly use_case_name: string
}

/**
 * The stop the answer is about. An Operator’s comes from the stopped list Needs you is made from. Needs you lists no stops for
 * someone who isn’t an Operator, so theirs comes from the workflows’ last runs, which their Workflows page shows as Stopped.
 */
function stopOf(useCaseId: string | null, operator: boolean, home: HomeOut | undefined, list: readonly UseCaseView[] | undefined): Stop | null | undefined {
  const asked = (id: string) => useCaseId === null || id === useCaseId
  if (operator) return home ? (home.stopped.find((item) => asked(item.use_case_id)) ?? null) : undefined
  if (!list) return undefined
  for (const { use_case_id, name, last_run } of list) {
    if (asked(use_case_id) && last_run?.state === 'failed' && last_run.reason !== null) return { run_id: last_run.run_id, use_case_name: name }
  }
  return null
}

/** What a card says about the run, read aloud once as the run moves: the name and where it is. */
const sayStage = (story: Pick<RunStory, 'stage'>, name: string): string => `${name}: ${stageWords(story.stage)}.`

/** The card's body for one story. Pure, so it can be drawn from a run's fixture events. */
export function RunCardView({ runId, name, story, beside }: { runId: string; name: string; story: RunStory | Omit<RunStory, 'useCase' | 'approvalId'>; beside: boolean }) {
  const { settled, model } = story
  const ended = settled !== null
  const failure = model.phase.state === 'failed' ? model.phase : null
  const safeId = `${runId}-safe`
  return (
    <Card
      title={name}
      pill={<RunPill pill={story.headline.pill} />}
      actions={
        <>
          <OpenButton variant="secondary" item={{ kind: 'run', id: runId }} to={`/runs/${runId}`}>
            Open
          </OpenButton>
          {failure ? <StopNext runId={runId} failure={failure} {...story.stopped} safeId={safeId} /> : null}
        </>
      }
    >
      {ended ? <SettledLine settled={settled} /> : beside ? null : <RunLine stations={story.stations} arrivedLive={story.arrivedLive} settled={null} small />}
      {failure ? <StopAnswers failure={failure} {...story.stopped} safeId={safeId} /> : story.answers.length > 0 ? <AnswerList answers={story.answers} /> : null}
    </Card>
  )
}

function LiveRunCard({ run, say, onStage }: { run: RunView; say: Say; onStage: (stage: RunStage) => void }) {
  const { live } = useLiveRun(run.run_id)
  const story = useRunStory(run, live)
  const beside = useShownInPanel({ kind: 'run', id: run.run_id })
  const ready = live.loaded
  const phrase = ready ? sayStage(story, run.use_case_name) : null
  useEffect(() => {
    if (phrase !== null) say(phrase)
  }, [phrase, say])
  useEffect(() => {
    if (ready) onStage(story.stage)
  }, [ready, story.stage, onStage])
  if (!ready) {
    return (
      <p className="muted" role="status">
        Reading the run
      </p>
    )
  }
  return <RunCardView runId={run.run_id} name={run.use_case_name} story={story} beside={beside} />
}

/**
 * Why it stopped, as the run card: fronted by the AI troubleshooter, the run’s line, then its three answers and Open, Report to
 * support and Retry. It follows the run’s stream, so after a retry the same card moves in place through retrying, waiting, done or
 * declined. The run is kept once found, because it leaves the stopped list the moment it is retried.
 */
function RunCardBody({ useCaseId, say, onStage }: { useCaseId: string | null; say: Say; onStage: (stage: RunStage) => void }) {
  const home = useHome()
  const me = useMe().data
  const useCases = useUseCases()
  const stopped = me === undefined ? undefined : stopOf(useCaseId, isOperator(me), home.data, useCases.data)
  const [pinned, setPinned] = useState<string | null>(null)
  if (pinned === null && stopped) setPinned(stopped.run_id)
  const runId = pinned ?? stopped?.run_id ?? null
  const run = useRun(runId ?? '')
  const nothing = stopped === null && pinned === null
  useEffect(() => {
    if (nothing) say('Nothing has stopped right now.')
  }, [nothing, say])
  if (runId === null && stopped === undefined) {
    return (
      <p className="muted" role="status">
        {home.isError || useCases.isError ? 'I couldn’t read the stopped workflows just now.' : 'Checking what stopped'}
      </p>
    )
  }
  if (runId === null) {
    return (
      <>
        <p>Nothing has stopped right now.</p>
        <ButtonLink to="/workflows">Open Workflows</ButtonLink>
      </>
    )
  }
  if (!run.data) {
    return (
      <p className="muted" role="status">
        {run.isError ? 'I couldn’t read that run just now.' : 'Reading the run'}
      </p>
    )
  }
  return <LiveRunCard run={run.data} say={say} onStage={onStage} />
}

/** The whole message: the AI troubleshooter’s face, whose mood follows the run, and the card column beside it. */
export function RunCardMessage({ useCaseId, say, leftovers }: { useCaseId: string | null; say: Say; leftovers: ReactNode }) {
  const [stage, setStage] = useState<RunStage>('stopped')
  return (
    <>
      <AgentFace id="troubleshooter" size={30} state={TROUBLE_FACE[stage]} />
      <div className={styles['cards']}>
        <span className="visually-hidden">AI troubleshooter: </span>
        {leftovers}
        <RunCardBody useCaseId={useCaseId} say={say} onStage={setStage} />
      </div>
    </>
  )
}
