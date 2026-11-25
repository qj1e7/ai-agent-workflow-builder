import { useState } from 'react'
import { useParams } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useDecideSetUp, useSetUpApproval } from '../../api/draftedQueries'
import { pressOnce, useLatch } from '../../api/latch'
import type { SetUpApprovalView, SetUpDeclineReason, SetUpDecisionIn } from '../../api/types'
import { ApiError } from '../../api/client'
import { Button, ButtonLink } from '../../ui/Button'
import { Flag, Touches, WhoApproves, Words } from '../explain/Report'
import { approvalPill, YOUR_YES } from '../run/approvalWords'
import { DraftPill } from '../home/Building'
import { NotFoundPage } from '../../shell/NotFoundPage'
import { approvedWords, declinedWords, setUpLine, type PillWords } from './drafted'
import { FixEvidence } from './FixEvidence'
import styles from './Drafted.module.css'

const notFound = (error: unknown): boolean => error instanceof ApiError && error.status === 404

export const PICK_A_REASON = 'Pick a reason first'

/** The page's one pill: the approval's own words, and the one an Approver who may decide reads, Needs your yes. */
export function setUpApprovalPill(view: Pick<SetUpApprovalView, 'approval' | 'you_can_decide'>): PillWords {
  switch (view.approval.status) {
    case 'waiting':
      return view.you_can_decide ? YOUR_YES : approvalPill({ is: 'open', step: 0, steps: 1, approvedBy: [] }, false)
    case 'approved':
      return approvalPill({ is: 'approved', by: [], at: null }, false)
    case 'declined':
      return approvalPill({ is: 'declined', record: { by: '', approvedBy: [], reason: null }, at: null }, false)
    case 'expired':
      return approvalPill({ is: 'expired' }, false)
    case 'replaced':
      return approvalPill({ is: 'cancelled' }, false)
  }
}

const GONE: Readonly<Record<'expired' | 'replaced', string>> = {
  expired: 'No one answered in time. Nothing was set up.',
  replaced: 'A newer revision replaced this one. Nothing was set up.',
}

function Outcome({ view }: { view: SetUpApprovalView }) {
  const { status } = view.approval
  if (status === 'declined') return <p className={styles['said']}>{declinedWords(view.approval)}</p>
  if (status === 'expired' || status === 'replaced') return <p className={styles['said']}>{GONE[status]}</p>
  const line = setUpLine(view.set_up)
  return (
    <>
      <p className={styles['ok']}>{approvedWords(view.approval)}</p>
      <p className={line.kind === 'set_up' ? styles['ok'] : styles['said']}>{line.words}</p>
      {line.kind === 'set_up' && line.useCaseId !== null ? (
        <p>
          <ButtonLink to={`/workflows/${encodeURIComponent(line.useCaseId)}`}>Open it</ButtonLink>
        </p>
      ) : null}
    </>
  )
}

function Decide({ view }: { view: SetUpApprovalView }) {
  const decide = useDecideSetUp(view.approval_id)
  const latch = useLatch()
  const words = useErrorWords()
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState<SetUpDeclineReason | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const send = (body: SetUpDecisionIn) => pressOnce(latch, (outcome) => decide.mutate(body, outcome), { onSuccess: () => setProblem(null), onError: (error) => setProblem(words(error)) })
  return (
    <>
      {declining ? (
        <div className={styles['more']}>
          <p className={styles['said']}>
            <b>Why?</b> <span className={styles['note']}>The person who asked for it will see it.</span>
          </p>
          <ul className={styles['reasons']} aria-label="Reasons">
            {view.decline_reasons.map((option) => (
              <li key={option}>
                <Button aria-pressed={reason === option} variant={reason === option ? 'primary' : 'secondary'} onClick={() => setReason(option as SetUpDeclineReason)}>
                  {option}
                </Button>
              </li>
            ))}
          </ul>
          <div className={styles['foot']}>
            <Button
              onClick={() => {
                setDeclining(false)
                setReason(null)
              }}
            >
              Cancel
            </Button>
            {reason === null ? (
              <span className={styles['stand']}>{PICK_A_REASON}</span>
            ) : (
              <Button variant="danger-outline" loading={decide.isPending} onClick={() => send({ verdict: 'decline', digest: view.digest, reason })}>
                Decline
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className={styles['foot']}>
          <Button variant="approve" loading={decide.isPending} onClick={() => send({ verdict: 'approve', digest: view.digest })}>
            Approve
          </Button>
          <Button onClick={() => setDeclining(true)}>Decline</Button>
        </div>
      )}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </>
  )
}

/**
 * What an Approver decides on for a draft: In short, the flags, what it reads, writes and posts, and who approves each write, all in
 * view. Approve and Decline show only to someone who may decide. Everyone else reads why not, in its place (principle 9).
 */
export function SetUpApproval({ view }: { view: SetUpApprovalView }) {
  const { report } = view
  const pill = setUpApprovalPill(view)
  const waiting = view.approval.status === 'waiting'
  return (
    <div className={styles['page']}>
      <div className={styles['pageHead']}>
        <div>
          <p className={styles['kind']}>{view.fix ? `Set-up approval, from ${view.fix.asked_by}’s request for a fix` : `Set-up approval, from ${view.approval.sent_by}’s draft`}</p>
          <h1 tabIndex={-1}>{view.name}</h1>
        </div>
        <DraftPill label={pill.label} tone={pill.tone} />
      </div>
      <p className={styles['said']} data-in-short>
        <Words segments={report.in_short} />
      </p>
      {view.fix ? <FixEvidence fix={view.fix} /> : null}
      {report.flags.length > 0 ? (
        <section className={styles['more']} aria-label="Flags">
          <h2 className={styles['kind']}>Flags</h2>
          <ul className={styles['rows']}>
            {report.flags.map((flag, index) => (
              <Flag key={index} flag={flag} />
            ))}
          </ul>
        </section>
      ) : null}
      <section className={styles['more']} aria-label="What it reads, writes and posts">
        <h2 className={styles['kind']}>What it reads, writes and posts</h2>
        <Touches touches={report.touches} />
      </section>
      <section className={styles['more']} aria-label="Who approves each write">
        <h2 className={styles['kind']}>Who approves each write</h2>
        <WhoApproves approves={report.approves} />
      </section>
      {waiting ? (
        view.you_can_decide ? (
          <Decide view={view} />
        ) : (
          <p className={styles['stand']}>{view.why_not}</p>
        )
      ) : (
        <Outcome view={view} />
      )}
    </div>
  )
}

export function SetUpApprovalRoute() {
  const { approvalId = '' } = useParams()
  const query = useSetUpApproval(approvalId)
  if (query.isPending) {
    return (
      <p className="muted" role="status">
        Loading
      </p>
    )
  }
  if (query.isError) {
    return notFound(query.error) ? (
      <NotFoundPage />
    ) : (
      <p role="alert">
        The approval could not be loaded. <Button onClick={() => void query.refetch()}>Try again</Button>
      </p>
    )
  }
  return <SetUpApproval key={query.data.approval_id} view={query.data} />
}
