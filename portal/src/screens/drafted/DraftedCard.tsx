import { useEffect, useState, type ReactNode } from 'react'
import { useErrorWords } from '../../api/context'
import { useDrafted, useSendDrafted, useSetUpAgain } from '../../api/draftedQueries'
import { pressOnce, useLatch } from '../../api/latch'
import type { DraftedWorkflowView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { AskTheTeam } from '../home/AskTheTeam'
import { DraftPill } from '../home/Building'
import { useAskForChange } from '../home/ChatProvider'
import { useMainButton } from '../home/primary'
import { Report, Words } from '../explain/Report'
import { RunLine } from '../run/RunLine'
import { workingWords } from '../run/words'
import { addedWords, approvedWords, CANCELLED_WAITING_WORDS, declinedWords, draftedPill, draftedTitle, flagsWords, revisionWords, setUpLine, settledWords, stationsOf, WAITING_WORDS } from './drafted'
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

function Head({ view, revision }: { view: Pick<DraftedWorkflowView, 'state'>; revision: number }) {
  const pill = draftedPill(view.state)
  return (
    <>
      <span className={styles['revision']}>{revisionWords(revision)}</span>
      {pill ? <DraftPill label={pill.label} tone={pill.tone} /> : null}
    </>
  )
}

function SetUpLines({ view }: { view: DraftedWorkflowView }) {
  const words = useErrorWords()
  const again = useSetUpAgain(view.drafted_id)
  const latch = useLatch()
  const [problem, setProblem] = useState<string | null>(null)
  const line = setUpLine(view.set_up)
  return (
    <>
      <p className={styles['ok']}>{approvedWords(view.approval)}</p>
      <p className={line.kind === 'set_up' ? styles['ok'] : styles['said']}>{line.words}</p>
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

function Foot({ view, onReport, onProblem }: { view: DraftedWorkflowView; onReport: () => void; onProblem: (words: string | null) => void }) {
  const main = useMainButton()
  const words = useErrorWords()
  const send = useSendDrafted(view.drafted_id)
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
  if (view.state === 'draft') {
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
    actions.push(
      view.can_send ? (
        <Button
          key="send"
          variant={main}
          loading={send.isPending}
          onClick={() => pressOnce(latch, (outcome) => send.mutate(view.revision, outcome), { onSuccess: () => onProblem(null), onError: (error) => onProblem(words(error)) })}
        >
          Send for approval
        </Button>
      ) : view.why_not_send ? (
        <span key="why" className={styles['stand']}>
          {view.why_not_send}
        </span>
      ) : null,
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

/** A revision that has been read: the step line, In short, what was added, the flags, and where it stands. */
function Revision({ view, revision }: { view: DraftedWorkflowView; revision: number }) {
  const [shown, setShown] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const report = view.report
  const stations = stationsOf(view.blocks)
  const added = report ? addedWords(report.fixed.length) : null
  return (
    <Card title={draftedTitle(view)} pill={<Head view={view} revision={revision} />} actions={<Foot view={view} onReport={() => setShown((was) => !was)} onProblem={setProblem} />}>
      {stations.length > 0 ? <RunLine stations={stations} arrivedLive={null} settled={null} small /> : null}
      {report ? (
        <p className={styles['said']} data-in-short>
          <Words segments={report.in_short} />
        </p>
      ) : null}
      {added ? <p className={styles['note']}>{added}</p> : null}
      {view.flags > 0 ? (
        <p className={styles['said']}>
          {flagsWords(view.flags)}{' '}
          <button type="button" className={styles['linkButton']} onClick={() => setShown(true)}>
            See them
          </button>
        </p>
      ) : null}
      {view.replaced_waiting ? <p className={styles['note']}>{CANCELLED_WAITING_WORDS}</p> : null}
      {view.state === 'waiting' ? <p className={styles['note']}>{WAITING_WORDS}</p> : null}
      {view.state === 'approved' ? <SetUpLines view={view} /> : null}
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
  if (revision < view.revision) {
    return (
      <Card title={draftedTitle(view)}>
        <p className={styles['note']}>{settledWords(revision, view.revision)}</p>
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
  return <Revision view={view} revision={revision} />
}
