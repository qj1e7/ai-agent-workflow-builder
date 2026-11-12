import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { operationLabel } from '../../api/labels'
import type { ApprovalView, WriteActionView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconCheck, IconLock } from '../../ui/icons'
import { TicketKeys } from '../jira/TicketKeys'
import { APPROVE, happensWords, openStep, type Decision } from './decision'
import { AskBox, QuestionThread } from './QuestionThread'
import { useFocusAfter, type Questions } from './questions'
import { approvalTitle, approveLabel, bodyOf, ticketKeysIn, titleOf, type NameOf } from './words'
import styles from './panels.module.css'

export const EXACT_WORDS = 'This is exactly what will be written, and nothing else.'
export const FOUND_NOTE = 'The agents wrote this to help you read. What will be written is listed above.'
export const NO_SUMMARY = 'The agents left no summary. Open what each agent did, below.'

function Change({ action }: { action: WriteActionView }) {
  const body = bodyOf(action)
  return (
    <div className={styles['ticket']}>
      <b>{titleOf(action) ?? operationLabel(action.operation)}</b>
      {body ? <span className={styles['body']}>{body}</span> : null}
    </div>
  )
}

function Row({ name, children }: { name: string; children: ReactNode }) {
  return (
    <dl className={styles['qa']}>
      <dt>{name}</dt>
      <dd>{children}</dd>
    </dl>
  )
}

/** What only the run page adds around the write: Why, Who asked and Your part (spec 10.4). */
export interface PageDetails {
  /** What the agents found. The activity keeps it after the approval stops carrying it. */
  readonly found: string
  /** The reader's part, from yourPart in decision.ts. Null once no step is open. */
  readonly part: string | null
  readonly askedBy: string
}

interface ApprovalGateProps {
  readonly approval: ApprovalView
  /** Null in the side panel, which shows everything that will be written and the decision, and leaves the rest for the page. */
  readonly page: PageDetails | null
  readonly decision: Pick<Decision, 'pending' | 'recorded' | 'error' | 'decide'>
  /** The quick reasons Decline offers, from declineReasons in decision.ts. */
  readonly reasons: readonly string[]
  /** Who sees the reason with the record, and answers questions, by name. */
  readonly requester: string
  readonly questions: Questions
  readonly me: string | undefined
  readonly nameOf: NameOf
}

/** Under Approve and Decline: the reasons Decline asks for, or the box Ask opens. Never both. */
type Opened = { readonly kind: 'decline'; readonly picked: string | null } | { readonly kind: 'ask' }

interface DeclineReasonsProps {
  readonly reasons: readonly string[]
  readonly requester: string
  readonly picked: string | null
  readonly pending: boolean
  readonly busy: boolean
  readonly onPick: (reason: string) => void
  readonly onDecline: () => void
  readonly onBack: () => void
}

/**
 * Decline asks why, with a few quick reasons, and needs none (spec 10.4). The reason is a note on the record. It adds no way to
 * approve, and the platform decides the decline the same with or without it.
 */
export function DeclineReasons({ reasons, requester, picked, pending, busy, onPick, onDecline, onBack }: DeclineReasonsProps) {
  const first = useRef<HTMLButtonElement>(null)
  const askId = useId()
  useEffect(() => first.current?.focus(), [])
  return (
    <div className={styles['decide']} role="group" aria-labelledby={askId}>
      <p id={askId}>
        <b>Why are you declining?</b> <span className={styles['muted']}>Optional. {requester} sees it with the record.</span>
      </p>
      <div className={styles['picks']}>
        {reasons.map((reason, index) => (
          <button key={reason} ref={index === 0 ? first : undefined} type="button" className={styles['pick']} aria-pressed={picked === reason} onClick={() => onPick(reason)}>
            {picked === reason ? <IconCheck size={14} /> : null}
            {reason}
          </button>
        ))}
      </div>
      <div className={styles['buttons']}>
        <Button variant="danger-outline" loading={pending} disabled={busy && !pending} onClick={onDecline}>
          Decline
        </Button>
        <Button disabled={busy} onClick={onBack}>
          Back
        </Button>
      </div>
    </div>
  )
}

/**
 * Exactly what will be written, from the approval route, so a slow stream never shows an old proposal. The summary around
 * it helps the reader. It is never the check: the platform checks the digest and the deciding person again at the write.
 */
export function ApprovalGate({ approval, page, decision, reasons, requester, questions, me, nameOf }: ApprovalGateProps) {
  // Once this person's decision is recorded, the gate offers them nothing more, though the run's own events may take a while to say so.
  // The question thread does not depend on it.
  const open = openStep(approval) !== null && decision.recorded === null
  const canDecide = approval.you_can_decide && open
  const busy = decision.pending !== null
  const [opened, setOpened] = useState<Opened | null>(null)
  const declineButton = useRef<HTMLButtonElement>(null)
  const askButton = useRef<HTMLButtonElement>(null)
  const backTo = useRef<Opened['kind'] | null>(null)
  const thread = useFocusAfter<HTMLHeadingElement>()
  useEffect(() => {
    if (opened !== null || backTo.current === null) return
    const to = backTo.current === 'ask' ? askButton : declineButton
    backTo.current = null
    to.current?.focus()
  }, [opened])
  const declining = opened?.kind === 'decline' ? opened : null
  const projects = approval.actions.flatMap((action) => (typeof action.target['project'] === 'string' ? [action.target['project']] : []))
  return (
    <div className={styles['panel']}>
      <Row name="What will change">
        <b className={styles['changeTitle']}>{approvalTitle(approval.actions)}</b>
        {approval.actions.map((action, index) => (
          <Change key={index} action={action} />
        ))}
        <p className={styles['note']}>{EXACT_WORDS}</p>
      </Row>
      {page ? (
        <>
          <Row name="Why">
            {page.found === '' ? (
              <span>{NO_SUMMARY}</span>
            ) : (
              <>
                <span className={styles['found']}>
                  <TicketKeys text={page.found} keys={ticketKeysIn(page.found, projects)} />
                </span>
                <p className={styles['note']}>{FOUND_NOTE}</p>
              </>
            )}
          </Row>
          <Row name="Who asked">{page.askedBy}</Row>
        </>
      ) : null}
      {open ? <Row name="What happens">{happensWords(approval, canDecide)}</Row> : null}
      {open && page?.part ? (
        <Row name="Your part">
          {canDecide ? (
            page.part
          ) : (
            <span className={styles['lock']}>
              <IconLock size={20} />
              <span>{page.part}</span>
            </span>
          )}
        </Row>
      ) : null}
      <QuestionThread approval={approval} me={me} nameOf={nameOf} answer={questions.answer} heading={thread} />
      {canDecide && declining ? (
        <DeclineReasons
          reasons={reasons}
          requester={requester}
          picked={declining.picked}
          pending={decision.pending === 'decline'}
          busy={busy}
          onPick={(reason) => setOpened({ kind: 'decline', picked: declining.picked === reason ? null : reason })}
          onDecline={() => decision.decide({ verdict: 'decline', reason: declining.picked })}
          onBack={() => {
            backTo.current = 'decline'
            setOpened(null)
          }}
        />
      ) : null}
      {canDecide && opened?.kind === 'ask' ? (
        <div className={styles['decide']}>
          <AskBox
            requester={requester}
            ask={questions.ask}
            onSent={() => {
              thread.request()
              setOpened(null)
            }}
            onCancel={() => {
              backTo.current = 'ask'
              setOpened(null)
            }}
          />
        </div>
      ) : null}
      {canDecide && !opened ? (
        <div className={styles['decide']}>
          <div className={styles['buttons']}>
            <Button
              variant="approve"
              icon={IconCheck}
              loading={decision.pending === 'approve'}
              disabled={busy && decision.pending !== 'approve'}
              onClick={() => decision.decide(APPROVE)}
            >
              {approveLabel(approval.actions)}
            </Button>
            <Button ref={declineButton} variant="danger-outline" disabled={busy} onClick={() => setOpened({ kind: 'decline', picked: null })}>
              Decline
            </Button>
          </div>
          <p className={styles['askLine']}>
            Not sure yet?{' '}
            <button
              ref={askButton}
              type="button"
              className={styles['linkButton']}
              aria-disabled={busy || undefined}
              onClick={() => {
                if (!busy) setOpened({ kind: 'ask' })
              }}
            >
              Ask {requester} a question
            </button>
          </p>
        </div>
      ) : null}
      {decision.error ? (
        <p className={styles['error']} role="alert">
          {decision.error}
        </p>
      ) : null}
    </div>
  )
}
