import { useState } from 'react'
import type { ApprovalActionView, ApprovalView } from '../../api/types'
import { recordWords, turnWords } from './approvalWords'
import { Change, DecideActions, Record } from './ApprovalGate'
import { canDecideNow, standingOf, type Decision } from './decision'
import { decidesLine, previewOf, wantsLine, type Tense } from './happened'
import { QuestionThread } from './QuestionThread'
import { useFocusAfter, type Questions } from './questions'
import type { NameOf, Party, StageFacts } from './words'
import styles from './RunDecision.module.css'
import panels from './panels.module.css'

/** One write as a small preview: its title, a one-line gist of its text, and the whole of it, exactly as it will be written, behind "Show full text". */
function Ticket({ action }: { action: ApprovalActionView }) {
  const { title, gist } = previewOf(action)
  const [open, setOpen] = useState(false)
  return (
    <details className={styles['ticket']} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span className={styles['preview']}>
          <b>{title}</b>
          {gist ? <span className={styles['gist']}>{gist}</span> : null}
        </span>
        <span className={styles['more']}>{open ? 'Hide full text' : 'Show full text'}</span>
      </summary>
      <div className={styles['full']}>
        <Change action={action} />
      </div>
    </details>
  )
}

export interface RunDecisionProps {
  readonly approval: ApprovalView
  /** What was found, built from the run's own facts. Null when the run read no one release. */
  readonly found: string | null
  readonly tense: Tense
  readonly decision: Pick<Decision, 'pending' | 'recorded' | 'steps' | 'error' | 'decide'>
  /** The run, for what happened after the approval. Null where the run isn't read. */
  readonly facts: StageFacts | null
  /** The quick reasons Decline offers, from declineReasons in decision.ts. */
  readonly reasons: readonly string[]
  /** Who sees the reason with the record, and answers questions, by name. */
  readonly requester: string
  readonly questions: Questions
  readonly me: string | undefined
  readonly party: Party | null
  readonly nameOf: NameOf
  /** What happens after a decline, from declinedNext in words.ts. */
  readonly next: string | null
  readonly now: Date
}

/**
 * What a run page and its side panel lead with, in every state: what was found, what the run wants to do or did and the ticket as a
 * small preview, then who decides and when they were asked. An Approver gets Approve, Decline and Ask in the same block. The status
 * is the page's top line, so it is not said again here, and the AI's words and what the run did not check are not on this page.
 * The platform checks the digest and the deciding person again at the write, so nothing here is the check.
 */
export function RunDecision({ approval, found, tense, decision, facts, reasons, requester, questions, me, nameOf, next, now }: RunDecisionProps) {
  const steps = decision.steps ?? approval.steps
  const standing = standingOf(steps)
  const canDecide = canDecideNow(approval, decision)
  // Once this person's decision is recorded, the request offers them nothing more, though the next read may take a while to say so.
  const whyNot = decision.recorded === null ? approval.why_not : 'decided_earlier_step'
  const thread = useFocusAfter<HTMLHeadingElement>()
  const turn = turnWords(standing, nameOf)
  const record = recordWords(standing, facts, nameOf, reasons, now)

  return (
    <div className={styles['decision']}>
      {found ? <p className={styles['found']}>{found}</p> : null}
      <p className={styles['wants']}>{wantsLine(approval.actions, tense)}</p>
      {approval.actions.map((action, index) => (
        <Ticket key={index} action={action} />
      ))}
      <div className={styles['who']}>
        {turn ? <p>{turn}</p> : null}
        {record !== null ? (
          <Record standing={standing} words={record} facts={facts} next={next} />
        ) : (
          <>
            <p>{decidesLine({ steps, canDecide, whyNot, now })}</p>
            {canDecide ? (
              <div className={panels['apprFoot']}>
                <DecideActions decision={decision} reasons={reasons} requester={requester} questions={questions} thread={thread} />
              </div>
            ) : null}
          </>
        )}
      </div>
      <QuestionThread approval={approval} me={me} nameOf={nameOf} answer={questions.answer} heading={thread} level={3} />
      {decision.error ? (
        <p className={panels['error']} role="alert">
          {decision.error}
        </p>
      ) : null}
    </div>
  )
}
