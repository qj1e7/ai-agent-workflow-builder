import { useEffect, useState, type ReactNode } from 'react'
import { useErrorWords } from '../../api/context'
import { useStartRun, useUseCase } from '../../api/queries'
import { useSetUp, useTestRunMarks, useTurnOn, type SetUp } from '../../api/workflowQueries'
import type { UseCaseView } from '../../api/types'
import { AgentFace } from '../../ui/AgentFace'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { cx } from '../../ui/cx'
import { IconCheck } from '../../ui/icons'
import { motionAllowed } from '../../ui/motion'
import { OpenButton } from '../../ui/OpenItem'
import { useShownInPanel } from '../../ui/sidePanel'
import { useLiveRun } from '../run/liveRun'
import { RunLine } from '../run/RunLine'
import { emptyModel, stationsOf, type RunModel } from '../run/runModel'
import { planOf } from '../run/useRunStory'
import { scheduleShort } from '../run/words'
import { nextRunAt } from '../workflows/times'
import { buildLine, buildStage, draftPill, LINE_STEP_MS, notesOf, replayAt, shownOf, testStatus, testStep, type BuildStage, type PillTone, type Replay } from './build'
import { useShowBesideOnWide } from './autoOpen'
import { PartsList, type Part } from './PartsList'
import runStyles from '../run/RunPage.module.css'
import styles from './SetupCard.module.css'

/** A draft's one pill: Draft, Building, Ready, On or Dropped. */
export function DraftPill({ label, tone }: { label: string; tone: PillTone }) {
  return (
    <span className={cx(runStyles['pill'], runStyles[tone])} data-draft-pill>
      {label}
    </span>
  )
}

/** The build log replayed with its real gaps, each line held at least the sketch's step. With reduced motion every line shows at once. */
export function useReplay(setUp: SetUp | undefined): Replay {
  const [now, setNow] = useState(() => Date.now())
  const replay = replayAt(setUp?.created.build_log ?? [], setUp?.at ?? 0, motionAllowed() ? LINE_STEP_MS : 0, now)
  useEffect(() => {
    if (replay.next === null) return
    const timer = setTimeout(() => setNow(Date.now()), Math.max(replay.next - Date.now(), 0))
    return () => clearTimeout(timer)
  }, [replay.next])
  return replay
}

function Followed({ runId, children }: { runId: string; children: (test: RunModel | null) => ReactNode }) {
  const { live } = useLiveRun(runId)
  return children(live.shown)
}

/** The test run's model from its own events, or null before the platform started one. */
export function TestRun({ runId, children }: { runId: string | null; children: (test: RunModel | null) => ReactNode }) {
  return runId === null ? children(null) : <Followed key={runId} runId={runId}>{children}</Followed>
}

/** Everything the card and the panel say about one set-up, from the same three sources: its log, its test run's events and the workflow. */
export interface Built {
  readonly setUp: SetUp | undefined
  readonly useCase: UseCaseView | undefined
  /** The workflow could not be read, so whether it is a draft, and so whether to test it, isn't known. */
  readonly unread: { readonly retry: () => void } | null
  readonly replay: Replay
  readonly stage: BuildStage
}

export function useBuilt(useCaseId: string, test: RunModel | null): Built {
  const setUp = useSetUp(useCaseId)
  const read = useUseCase(useCaseId)
  const useCase = read.data
  const replay = useReplay(setUp)
  const unread = read.isError && !useCase ? { retry: () => void read.refetch() } : null
  return { setUp, useCase, unread, replay, stage: buildStage(replay.done, (setUp?.testRunId ?? null) !== null, test?.phase ?? null, useCase?.state) }
}

function firstRunWords(useCase: UseCaseView | undefined, now: Date): string {
  const next = useCase?.next_run_at
  return next ? `On. First run ${nextRunAt(next, now, useCase.schedule?.time_zone)}.` : 'On.'
}

interface BuildingProps {
  readonly useCaseId: string
  readonly title: string
  /** What it understood, as words now: Watch, When, Then and each cross. */
  readonly parts: readonly Part[]
  readonly newAgents: readonly string[]
  readonly draftKept: boolean
}

/**
 * The set-up card once Set up made the workflow as a draft. Its line appears as the build log says the blocks were added, the
 * safety checker's note when it added the yes, then the Tester's test run moves it from its own events. A test asks nobody and
 * writes nothing. Turn it on shows On only once the platform answers that the workflow is on.
 */
export function Building(props: BuildingProps) {
  const setUp = useSetUp(props.useCaseId)
  const runId = setUp?.testRunId ?? null
  const [problem, setProblem] = useState<string | null>(null)
  const start = useStartRun()
  const marks = useTestRunMarks()
  const turnOn = useTurnOn()
  const words = useErrorWords()
  useShowBesideOnWide({ kind: 'build', id: props.useCaseId })

  // The key and whether it was asked with live with the set-up, not the card, so a card drawn again never starts a second test run.
  const startTest = (life: UseCaseView['state'] | undefined, replayed: boolean) => {
    if (testStep(setUp, replayed, life) !== 'start' || !setUp) return
    const key = setUp.testKey
    marks.asked(props.useCaseId, key)
    setProblem(null)
    start.mutate(
      { useCaseId: props.useCaseId, idempotencyKey: key, test: true },
      { onSuccess: (run) => marks.started(props.useCaseId, run.run_id), onError: (error) => setProblem(`Could not start the test run. ${words(error)}`) },
    )
  }
  const pressTurnOn = () => {
    setProblem(null)
    turnOn.mutate(props.useCaseId, { onError: (error) => setProblem(`Could not turn it on. ${words(error)}`) })
  }

  return (
    <TestRun runId={runId}>
      {(test) => (
        <BuildingCard
          {...props}
          test={test}
          runId={runId}
          problem={problem}
          starting={start.isPending}
          turning={turnOn.isPending}
          onReplayed={startTest}
          onTestAgain={() => {
            setProblem(null)
            marks.again(props.useCaseId)
          }}
          onTurnOn={pressTurnOn}
        />
      )}
    </TestRun>
  )
}

export interface CardProps extends BuildingProps {
  readonly test: RunModel | null
  readonly runId: string | null
  readonly problem: string | null
  readonly starting: boolean
  readonly turning: boolean
  /** On every draw: the test run starts here, once, after the log has replayed, while the workflow is a draft. */
  readonly onReplayed: (life: UseCaseView['state'] | undefined, replayed: boolean) => void
  readonly onTestAgain: () => void
  readonly onTurnOn: () => void
}

export function BuildingCard({ useCaseId, title, parts, newAgents, draftKept, test, runId, problem, starting, turning, onReplayed, onTestAgain, onTurnOn }: CardProps) {
  const { setUp, useCase, unread, replay, stage } = useBuilt(useCaseId, test)
  const beside = useShownInPanel({ kind: 'build', id: useCaseId })
  const [now] = useState(() => new Date())
  const life = useCase?.state
  useEffect(() => {
    onReplayed(life, replay.done)
  })

  const log = setUp?.created.build_log ?? []
  const shown = shownOf(log, replay.lines, replay.done)
  const stations = stationsOf(test ?? emptyModel, planOf(useCase), useCase?.schedule ? scheduleShort(useCase.schedule) : 'Start')
  const line = buildLine(stations, log, shown, test !== null && test.seq > 0, stage.kind === 'on')
  const notes = notesOf(replay.lines)
  const result = test ? testStatus(test) : null

  let status: ReactNode
  let actions: ReactNode
  const lost = setUp === undefined && stage.kind !== 'on'
  const pill = lost ? draftPill({ kind: 'stopped' }) : draftPill(stage)
  switch (unread ? 'unread' : lost ? 'lost' : stage.kind) {
    case 'unread':
      status = <span className={styles['bad']}>I couldn’t read the workflow just now, so the test run waits.</span>
      actions = <Button onClick={unread?.retry}>Try again</Button>
      break
    case 'lost':
      // The set-up's answer lives only as long as this visit. Without it no test run can start here, so the card says where to carry on.
      status = 'Saved as a draft. Open it to test it and turn it on.'
      actions = (
        <OpenButton item={{ kind: 'workflow', id: useCaseId }} to={`/workflows/${encodeURIComponent(useCaseId)}`}>
          Open<span className="visually-hidden"> {title}</span>
        </OpenButton>
      )
      break
    case 'laying_out':
    case 'saved':
      status = problem ? <span className={styles['bad']}>{problem}</span> : (replay.lines.findLast((one) => one.kind === 'status')?.text ?? (stage.kind === 'saved' ? 'Saved as a draft.' : 'Starting…'))
      actions = problem ? (
        <Button variant="primary" loading={starting} onClick={onTestAgain}>
          Test again
        </Button>
      ) : undefined
      break
    case 'testing':
      status = (
        <>
          <AgentFace id="tester" display="Tester" size={20} state="working" />
          Test run…
        </>
      )
      break
    case 'passed':
      status = (
        <span className={styles['good']}>
          <IconCheck size={15} />
          {result?.text}
        </span>
      )
      actions = (
        <Button variant="primary" loading={turning} onClick={onTurnOn}>
          Turn it on
        </Button>
      )
      break
    case 'stopped':
      status = <span className={styles['bad']}>{result?.text}</span>
      actions = (
        <>
          {runId ? (
            <OpenButton item={{ kind: 'run', id: runId }} to={`/runs/${runId}`}>
              Open<span className="visually-hidden"> the test run</span>
            </OpenButton>
          ) : null}
          <Button variant="primary" loading={starting} onClick={onTestAgain}>
            Test again
          </Button>
        </>
      )
      break
    case 'on':
      status = (
        <span className={styles['good']}>
          <IconCheck size={15} />
          {firstRunWords(useCase, now)}
        </span>
      )
      break
  }

  return (
    <Card title={title} pill={<DraftPill label={pill.label} tone={pill.tone} />} status={<span role="status">{status}</span>} actions={actions}>
      <PartsList parts={parts} short />
      {beside ? null : <RunLine stations={line.stations} arrivedLive={null} settled={null} small hidden={line.hidden} added={line.added} />}
      {notes.map((note) => (
        <p key={note} className={styles['note']}>
          <AgentFace id="safety_checker" display="Safety checker" size={20} state={stage.kind === 'laying_out' ? 'working' : 'success'} />
          {note}
        </p>
      ))}
      {newAgents.length > 0 ? <p className="muted">{newAgents.length === 1 ? `The ${newAgents[0] ?? ''} is saved under How it works, in Settings.` : `${newAgents.join(' and ')} are saved under How it works, in Settings.`}</p> : null}
      {draftKept ? <p className="muted">Your saved draft of this card is still on Workflows. Discard it there.</p> : null}
      {problem && stage.kind !== 'saved' && stage.kind !== 'laying_out' ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </Card>
  )
}
