import { useEffect, useId, useRef, useState } from 'react'
import type { ApprovalActionView } from '../../api/types'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { IconCheck } from '../../ui/icons'
import { fieldRows, whereWords } from './approvalWords'
import { APPROVE, type Decision, type Standing } from './decision'
import { AskBox } from './QuestionThread'
import { useFocusAfter, type Questions } from './questions'
import type { StageFacts } from './words'
import styles from './panels.module.css'

/** One write, exactly as the request holds it: where it goes, then every field it carries, so nothing written is hidden. */
export function Change({ action }: { action: ApprovalActionView }) {
  return (
    <dl className={styles['chg']}>
      <div>
        <dt>Where</dt>
        <dd>{whereWords(action)}</dd>
      </div>
      {fieldRows(action.fields).map(({ key, label, value }) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd className={key === 'body' ? styles['chgBody'] : undefined}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

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
 * Decline asks why, with a few quick reasons, and needs none. The reason is a note on the record. It adds no way to approve, and
 * the platform decides the decline the same with or without it. The second Decline is the confirmation.
 */
export function DeclineReasons({ reasons, requester, picked, pending, busy, onPick, onDecline, onBack }: DeclineReasonsProps) {
  const first = useRef<HTMLButtonElement>(null)
  const askId = useId()
  useEffect(() => first.current?.focus(), [])
  return (
    <div className={styles['decide']} role="group" aria-labelledby={askId}>
      <p id={askId}>
        <b>Why?</b> <span className={styles['muted']}>Optional. {requester} will see it.</span>
      </p>
      <div className={styles['picks']}>
        {reasons.map((reason, index) => (
          <button key={reason} ref={index === 0 ? first : undefined} type="button" className={styles['pick']} aria-pressed={picked === reason} onClick={() => onPick(reason)}>
            {picked === reason ? <IconCheck size={14} /> : null}
            {reason}
          </button>
        ))}
      </div>
      <div className={cx(styles['buttons'], styles['end'])}>
        <Button disabled={busy} onClick={onBack}>
          Back
        </Button>
        <Button variant="danger-outline" loading={pending} disabled={busy && !pending} onClick={onDecline}>
          Decline
        </Button>
      </div>
    </div>
  )
}

/** Under the record, the Ask box or Decline's reasons open in place of the buttons. Never both. */
type Opened = { readonly kind: 'decline'; readonly picked: string | null } | { readonly kind: 'ask' }

/** The record once the request is decided or over, with a stamp once the write is made. */
export function Record({ standing, words, facts, next }: { standing: Standing; words: string; facts: StageFacts | null; next: string | null }) {
  const made = standing.is === 'approved' && facts?.state === 'succeeded' && facts.count > 0
  return (
    <>
      <p className={cx(styles['record'], standing.is === 'approved' && styles['okRecord'], made && styles['stamped'])}>
        {standing.is === 'approved' ? <IconCheck size={16} /> : null}
        <span>{words}</span>
        {made ? (
          <span className={styles['stamp']} aria-hidden="true">
            {facts.tickets ? 'Created' : 'Written'}
          </span>
        ) : null}
      </p>
      {standing.is === 'declined' && next ? <p className={styles['muted']}>{next}</p> : null}
    </>
  )
}

export interface DecideActionsProps {
  readonly decision: Pick<Decision, 'pending' | 'error' | 'decide'>
  readonly reasons: readonly string[]
  readonly requester: string
  readonly questions: Questions
  /** The question thread's heading, which takes focus once a question is sent. */
  readonly thread: ReturnType<typeof useFocusAfter<HTMLHeadingElement>>
}

/**
 * What an Approver does about a request that waits: Approve, the one main button, with Decline and "Ask {name}" beside it. Decline
 * asks why first, and Ask opens its box, each in place of the buttons, and Back puts focus back where it was.
 */
export function DecideActions({ decision, reasons, requester, questions, thread }: DecideActionsProps) {
  const busy = decision.pending !== null
  const [opened, setOpened] = useState<Opened | null>(null)
  const declineButton = useRef<HTMLButtonElement>(null)
  const askButton = useRef<HTMLButtonElement>(null)
  const backTo = useRef<Opened['kind'] | null>(null)
  useEffect(() => {
    if (opened !== null || backTo.current === null) return
    const to = backTo.current === 'ask' ? askButton : declineButton
    backTo.current = null
    to.current?.focus()
  }, [opened])
  const declining = opened?.kind === 'decline' ? opened : null
  if (declining) {
    return (
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
    )
  }
  if (opened?.kind === 'ask') {
    return (
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
    )
  }
  return (
    <>
      <Button ref={askButton} disabled={busy} onClick={() => setOpened({ kind: 'ask' })}>
        Ask {requester}
      </Button>
      <span className={cx(styles['buttons'], styles['end'])}>
        <Button variant="primary" loading={decision.pending === 'approve'} disabled={busy && decision.pending !== 'approve'} onClick={() => decision.decide(APPROVE)}>
          Approve
        </Button>
        <Button ref={declineButton} disabled={busy} onClick={() => setOpened({ kind: 'decline', picked: null })}>
          Decline
        </Button>
      </span>
    </>
  )
}
