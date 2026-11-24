import { useEffect, useState, type ReactNode } from 'react'
import { useErrorWords } from '../../api/context'
import { useDoneInN8n, useDrafted, useEditInN8n, useSendDrafted, useSetUpAgain, useSimulateAgain } from '../../api/draftedQueries'
import { pressOnce, useLatch } from '../../api/latch'
import { useUseCase } from '../../api/queries'
import type { DraftedWorkflowView, SimulationView, UseCaseState } from '../../api/types'
import { useHoldTurnOn, useSetUp } from '../../api/workflowQueries'
import { Button, ButtonAnchor, ButtonLink } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { AskTheTeam } from '../home/AskTheTeam'
import { Building, DraftPill } from '../home/Building'
import { useAskForChange, useShowRevision } from '../home/ChatProvider'
import { useMainButton } from '../home/primary'
import { Report, Words } from '../explain/Report'
import { RunLine } from '../run/RunLine'
import { WithN8nLogin } from '../workflows/N8nLoginHint'
import { workingWords } from '../run/words'
import {
  addedWords,
  approvedWords,
  CANCELLED_WAITING_WORDS,
  checkedOnceWords,
  declinedWords,
  draftedPill,
  draftedTitle,
  flagsWords,
  inN8nWords,
  ONE_TIME_CHECK,
  revisionWords,
  setUpLine,
  settledWords,
  stationsOf,
  TURN_ON_NOW,
  WAITING_FOR_CHECK,
} from './drafted'
import { DraftedSettings } from './DraftedSettings'
import { SimulationResult } from './SimulationResult'
import styles from './Drafted.module.css'

const TICK_MS = 1000

/** Time going, from when the drafter started. It says nothing else, since only the platform knows what the drafter is doing. */
function Elapsed({ since }: { since: string | null }) {
  const [start] = useState(() => (since === null ? Date.now() : Date.parse(since)))
  const [words, setWords] = useState(() => workingWords(start, Date.now(), false))
  useEffect(() => {
    const timer = setInterval(() => setWords(workingWords(start, Date.now(), false)), TICK_MS)
    return () => clearInterval(timer)
  }, [start])
  return (
    <p className={styles['note']} role="status">
      {words}
    </p>
  )
}

function Head({ view, revision, life }: { view: Pick<DraftedWorkflowView, 'state'> & { in_n8n?: DraftedWorkflowView['in_n8n'] }; revision: number; life?: UseCaseState | undefined }) {
  const pill = draftedPill(view.state, view.in_n8n != null, life)
  return (
    <>
      <span className={styles['revision']}>{revisionWords(revision)}</span>
      {pill ? <DraftPill label={pill.label} tone={pill.tone} /> : null}
    </>
  )
}

/** The workflow an approved revision was set up as, once n8n holds it, or null. */
const setUpAs = (view: DraftedWorkflowView): string | null => (view.state === 'approved' && view.set_up?.state === 'set_up' ? view.set_up.use_case_id : null)

/** Turn on works as on any set-up card once the platform says the workflow it was set up as is a Draft: never while unread or gone. */
const turnsOnNow = (view: DraftedWorkflowView, life: UseCaseState | undefined): boolean => setUpAs(view) !== null && life === 'draft'

/** The one-time check, one line on the card (ADR 0053, item 3): that it comes before the first run, then who gave it. */
function CheckLine({ view }: { view: DraftedWorkflowView }) {
  if (view.state !== 'approved') {
    return (
      <p className={styles['said']} data-check>
        {ONE_TIME_CHECK}
      </p>
    )
  }
  const by = view.approval?.decided_by ?? null
  return (
    <p className={styles['ok']} data-check>
      {by === null ? approvedWords(view.approval) : checkedOnceWords(by)}
    </p>
  )
}

/** Where an approved set-up stands. A set-up refused or given up leaves a draft, which says why. Once set up, Turn on is next. */
function SetUpLines({ view, life }: { view: DraftedWorkflowView; life?: UseCaseState | undefined }) {
  const words = useErrorWords()
  const again = useSetUpAgain(view.drafted_id)
  const latch = useLatch()
  const [problem, setProblem] = useState<string | null>(null)
  const line = setUpLine(view.set_up)
  if (line.kind === 'set_up') return turnsOnNow(view, life) ? <p className={styles['said']}>{TURN_ON_NOW}</p> : null
  return (
    <>
      <p className={styles['said']}>{line.words}</p>
      {line.kind === 'failed' ? (
        <p>
          <Button loading={again.isPending} onClick={() => pressOnce(latch, (outcome) => again.mutate(undefined, outcome), { onError: (error) => setProblem(words(error)) })}>
            Try again
          </Button>
        </p>
      ) : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </>
  )
}

/** The buttons while the draft is open in n8n: for the person who opened it, a link to it and Done in n8n. Anyone else has the words in the status. */
function InN8nActions({ view, onProblem }: { view: DraftedWorkflowView; onProblem: (words: string | null) => void }) {
  const main = useMainButton()
  const words = useErrorWords()
  const done = useDoneInN8n(view.drafted_id)
  const latch = useLatch()
  const showRevision = useShowRevision()
  const editor = view.in_n8n?.editor_url ?? null
  if (editor === null) return null
  return (
    <>
      <WithN8nLogin key="open-n8n">
        <ButtonAnchor href={editor}>Open n8n</ButtonAnchor>
      </WithN8nLogin>
      <Button
        key="done"
        variant={main}
        loading={done.isPending}
        onClick={() =>
          pressOnce<DraftedWorkflowView>(latch, (outcome) => done.mutate(undefined, outcome), {
            onSuccess: (next) => {
              onProblem(null)
              showRevision?.(next.drafted_id, next.card_revision)
            },
            onError: (error) => onProblem(words(error)),
          })
        }
      >
        Done in n8n
      </Button>
    </>
  )
}

function EditInN8n({ view, onProblem }: { view: DraftedWorkflowView; onProblem: (words: string | null) => void }) {
  const words = useErrorWords()
  const edit = useEditInN8n(view.drafted_id)
  const latch = useLatch()
  return (
    <Button
      key="edit-n8n"
      loading={edit.isPending}
      onClick={() => pressOnce(latch, (outcome) => edit.mutate(view.revision, outcome), { onSuccess: () => onProblem(null), onError: (error) => onProblem(words(error)) })}
    >
      Edit in n8n
    </Button>
  )
}

function Foot({ view, life, onReport, onProblem }: { view: DraftedWorkflowView; life: UseCaseState | undefined; onReport: () => void; onProblem: (words: string | null) => void }) {
  const main = useMainButton()
  const words = useErrorWords()
  const send = useSendDrafted(view.drafted_id)
  const holdTurnOn = useHoldTurnOn()
  const latch = useLatch()
  const askForChange = useAskForChange()
  const line = setUpLine(view.set_up)
  const open = view.state === 'approved' && line.kind === 'set_up' && line.useCaseId !== null ? line.useCaseId : null
  const report = (
    <Button key="report" onClick={onReport}>
      See the report
    </Button>
  )
  const actions: ReactNode[] = [report]
  const inN8n = view.state === 'draft' && view.in_n8n !== null
  if (inN8n) {
    actions.push(<InN8nActions key="in-n8n" view={view} onProblem={onProblem} />)
  } else if (view.state === 'draft') {
    if (askForChange) {
      actions.push(
        <Button
          key="change"
          onClick={() => {
            askForChange({ draftedId: view.drafted_id, name: view.name ?? 'the workflow', revision: view.revision })
            setTimeout(() => document.getElementById('planner-box')?.focus(), 0)
          }}
        >
          Ask for a change
        </Button>,
      )
    }
    if (view.can_edit_in_n8n) actions.push(<EditInN8n key="edit" view={view} onProblem={onProblem} />)
    // Before the one-time check, Turn on sends the revision for its set-up approval (ADR 0051).
    actions.push(
      view.can_send ? (
        <Button
          key="send"
          variant={main}
          loading={send.isPending}
          onClick={() => pressOnce(latch, (outcome) => send.mutate(view.revision, outcome), { onSuccess: () => onProblem(null), onError: (error) => onProblem(words(error)) })}
        >
          Turn on
        </Button>
      ) : view.why_not_send ? (
        <span key="why" className={styles['stand']}>
          {view.why_not_send}
        </span>
      ) : null,
    )
  }
  const setUpId = setUpAs(view)
  if (setUpId !== null && turnsOnNow(view, life)) {
    actions.push(
      <Button key="turn-on" variant={main} onClick={() => holdTurnOn(setUpId)}>
        Turn on
      </Button>,
    )
  }
  if (open !== null) {
    actions.push(
      <ButtonLink key="open" to={`/workflows/${encodeURIComponent(open)}`}>
        Open it
      </ButtonLink>,
    )
  }
  return <>{actions}</>
}

/** The newest revision tried on practice systems. Try again asks for this revision, so a newer one is never tried by it. */
function DraftedSimulation({ view, simulation }: { view: DraftedWorkflowView; simulation: SimulationView }) {
  const again = useSimulateAgain(view.drafted_id)
  return <SimulationResult simulation={simulation} tryAgain={{ pending: again.isPending, press: (outcome) => again.mutate(view.revision, outcome) }} />
}

/** A revision that has been read: the step line, In short, what was added, the flags, and where it stands. */
function Revision({ view }: { view: DraftedWorkflowView }) {
  const [shown, setShown] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const setUpId = setUpAs(view)
  const life = useUseCase(setUpId ?? '', setUpId !== null).data?.state
  const pressed = useSetUp(setUpId ?? '') !== undefined
  if (setUpId !== null && pressed) return <Building useCaseId={setUpId} title={draftedTitle(view)} parts={[]} newAgents={[]} draftKept={false} />
  const report = view.report
  const stations = stationsOf(view.blocks)
  const added = report ? addedWords(report.fixed.length) : null
  return (
    <Card
      title={draftedTitle(view)}
      pill={<Head view={view} revision={view.revision} life={life} />}
      status={inN8nWords(view) ?? undefined}
      actions={<Foot view={view} life={life} onReport={() => setShown((was) => !was)} onProblem={setProblem} />}
    >
      {stations.length > 0 ? <RunLine stations={stations} arrivedLive={null} settled={null} small /> : null}
      {report ? (
        <p className={styles['said']} data-in-short>
          <Words segments={report.in_short} />
        </p>
      ) : null}
      {view.simulation ? <DraftedSimulation view={view} simulation={view.simulation} /> : null}
      {added ? <p className={styles['note']}>{added}</p> : null}
      {view.flags > 0 ? (
        <p className={styles['said']}>
          {flagsWords(view.flags)}{' '}
          <button type="button" className={styles['linkButton']} onClick={() => setShown(true)}>
            See them
          </button>
        </p>
      ) : null}
      <CheckLine view={view} />
      {view.replaced_waiting ? <p className={styles['note']}>{CANCELLED_WAITING_WORDS}</p> : null}
      {view.state === 'waiting' ? <p className={styles['note']}>{WAITING_FOR_CHECK}</p> : null}
      {view.state === 'approved' ? <SetUpLines view={view} life={life} /> : null}
      {view.state === 'draft' && view.set_up !== null ? <SetUpLines view={view} /> : null}
      {view.state === 'draft' && view.notes.length > 0 ? (
        <ul className={styles['notes']} data-n8n-notes>
          {view.notes.map((note) => (
            <li key={note} className={styles['note']}>
              {note}
            </li>
          ))}
        </ul>
      ) : null}
      <DraftedSettings view={view} />
      {view.state === 'declined' ? <p className={styles['said']}>{declinedWords(view.approval)}</p> : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      {shown && report ? <Report report={report} /> : null}
    </Card>
  )
}

/**
 * The drafted workflow's card, from the platform's own account of it (ADR 0051). Each card knows its revision: once a newer one
 * exists, an older card settles into one line, so only the newest asks anything.
 */
export function DraftedCard({ draftedId, revision }: { draftedId: string; revision: number }) {
  const query = useDrafted(draftedId)
  const view = query.data
  if (view === undefined) {
    return (
      <Card title="Drafting it as an n8n workflow" pill={<Head view={{ state: 'drafting' }} revision={revision} />}>
        {query.isError ? (
          <p className={styles['problem']} role="alert">
            I couldn’t read the draft. <Button onClick={() => void query.refetch()}>Try again</Button>
          </p>
        ) : (
          <Elapsed since={null} />
        )}
      </Card>
    )
  }
  if (revision < view.card_revision) {
    return (
      <Card title={draftedTitle(view)}>
        <p className={styles['note']}>{settledWords(revision, view.card_revision)}</p>
      </Card>
    )
  }
  if (view.state === 'drafting' || revision > view.revision) {
    return (
      <Card title={draftedTitle(view)} pill={<Head view={{ state: 'drafting' }} revision={revision} />}>
        <Elapsed since={view.state === 'drafting' ? view.started_at : null} />
      </Card>
    )
  }
  if (view.state === 'not_drafted') {
    const said = view.said ?? 'I couldn’t draft that.'
    return (
      <Card title={draftedTitle(view)} pill={<Head view={view} revision={revision} />} foot={<AskTheTeam capability="Draft an n8n workflow" starter={`I asked the Planner for: ${view.words}\n\n${said}`} />}>
        <p className={styles['said']}>{said}</p>
      </Card>
    )
  }
  return <Revision view={view} />
}
