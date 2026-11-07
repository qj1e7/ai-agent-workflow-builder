import type { ReactNode } from 'react'
import { operationLabel } from '../../api/labels'
import type { ApprovalView, WriteActionView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconCheck, IconLock } from '../../ui/icons'
import { TicketKeys } from '../jira/TicketKeys'
import { happensWords, openStep, type Decision } from './decision'
import { approveLabel, bodyOf, proposalTitle, ticketKeysIn, titleOf } from './words'
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

interface ApprovalGateProps {
  readonly approval: ApprovalView
  /** What the agents found. The activity keeps it after the approval stops carrying it. */
  readonly found: string
  /** The reader's part, from yourPart in decision.ts. Null once no step is open. */
  readonly part: string | null
  readonly askedBy: string
  readonly decision: Pick<Decision, 'pending' | 'error' | 'decide'>
}

/**
 * Exactly what will be written, from the approval route, so a slow stream never shows an old proposal. The summary around
 * it helps the reader. It is never the check: the platform checks the digest and the deciding person again at the write.
 */
export function ApprovalGate({ approval, found, part, askedBy, decision }: ApprovalGateProps) {
  const open = openStep(approval) !== null
  const canDecide = approval.you_can_decide && open
  const busy = decision.pending !== null
  const projects = approval.actions.flatMap((action) => (typeof action.target['project'] === 'string' ? [action.target['project']] : []))
  return (
    <div className={styles['panel']}>
      <Row name="What will change">
        <b className={styles['changeTitle']}>{proposalTitle(approval.actions)}</b>
        {approval.actions.map((action, index) => (
          <Change key={index} action={action} />
        ))}
        <p className={styles['note']}>{EXACT_WORDS}</p>
      </Row>
      <Row name="Why">
        {found === '' ? (
          <span>{NO_SUMMARY}</span>
        ) : (
          <>
            <span className={styles['found']}>
              <TicketKeys text={found} keys={ticketKeysIn(found, projects)} />
            </span>
            <p className={styles['note']}>{FOUND_NOTE}</p>
          </>
        )}
      </Row>
      <Row name="Who asked">{askedBy}</Row>
      {open ? <Row name="What happens">{happensWords(approval, canDecide)}</Row> : null}
      {open && part ? (
        <Row name="Your part">
          {canDecide ? (
            part
          ) : (
            <span className={styles['lock']}>
              <IconLock size={20} />
              <span>{part}</span>
            </span>
          )}
        </Row>
      ) : null}
      {canDecide ? (
        <div className={styles['buttons']}>
          <Button
            variant="approve"
            icon={IconCheck}
            loading={decision.pending === 'approve'}
            disabled={busy && decision.pending !== 'approve'}
            onClick={() => decision.decide('approve')}
          >
            {approveLabel(approval.actions)}
          </Button>
          <Button
            variant="danger-outline"
            loading={decision.pending === 'decline'}
            disabled={busy && decision.pending !== 'decline'}
            onClick={() => decision.decide('decline')}
          >
            Decline
          </Button>
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
