import { operationLabel } from '../../api/labels'
import type { ApprovalView, WriteActionView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconCheck, IconLock } from '../../ui/icons'
import type { Decision } from './decision'
import { openStep } from './decision'
import { approveLabel, bodyOf, proposalTitle, titleOf } from './words'
import styles from './panels.module.css'

export const EXACT_WORDS = 'This is exactly what will be written, and nothing else.'

function Change({ action }: { action: WriteActionView }) {
  const body = bodyOf(action)
  return (
    <div className={styles['ticket']}>
      <b>{titleOf(action) ?? operationLabel(action.operation)}</b>
      {body ? <span className={styles['body']}>{body}</span> : null}
    </div>
  )
}

interface ApprovalGateProps {
  readonly approval: ApprovalView
  readonly cannotDecide: string
  readonly decision: Pick<Decision, 'pending' | 'error' | 'decide'>
}

/**
 * Exactly what will be written, from the approval route, so a slow stream never shows an old proposal.
 */
export function ApprovalGate({ approval, cannotDecide, decision }: ApprovalGateProps) {
  const open = openStep(approval) !== null
  const canDecide = approval.you_can_decide && open
  const busy = decision.pending !== null
  return (
    <div className={styles['panel']}>
      <h2>{proposalTitle(approval.actions)}</h2>
      {approval.actions.map((action, index) => (
        <Change key={index} action={action} />
      ))}
      <p className={styles['note']}>{EXACT_WORDS}</p>
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
      ) : open ? (
        <div className={styles['lock']}>
          <IconLock size={20} />
          <p>{cannotDecide}</p>
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
