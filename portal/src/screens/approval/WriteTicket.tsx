import type { WriteActionView } from '../../api/types'
import { IconCheck, IconLock, IconShield, IconUnlock, IconX, type Icon } from '../../ui/icons'
import type { TicketStatus } from './ticketStatus'
import { describeAction } from './writeAction'
import styles from './WriteTicket.module.css'

interface WriteTicketProps {
  action: WriteActionView
  position: { index: number; total: number }
  status: TicketStatus
}

const statusWords: Record<TicketStatus['kind'], { line: (status: TicketStatus) => string; tag: string; icon: Icon }> = {
  draft: { line: () => 'Not written yet', tag: 'Draft', icon: IconLock },
  writing: { line: () => 'Being written', tag: 'Approved', icon: IconUnlock },
  written: { line: (status) => (status.kind === 'written' ? `Written as ${status.key}` : ''), tag: 'Written', icon: IconCheck },
  declined: { line: () => 'Not written', tag: 'Declined', icon: IconX },
}

export function WriteTicket({ action, position, status }: WriteTicketProps) {
  const { rows, title, body } = describeAction(action)
  const words = statusWords[status.kind]
  const Mark = words.icon
  return (
    <article className={styles['ticket']} aria-label={position.total > 1 ? `Write ${position.index + 1} of ${position.total}` : 'The write'}>
      <header className={styles['head']}>
        <span className={styles['unwritten']}>
          <Mark size={16} />
          {words.line(status)}
        </span>
        <span className={styles['tag']}>{position.total > 1 ? `${words.tag} ${position.index + 1} of ${position.total}` : words.tag}</span>
      </header>
      <div className={styles['content']}>
        <dl className={styles['rows']}>
          {rows.map((row) => (
            <div key={row.label} className={styles['row']}>
              <dt className="plan-voice">{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        {title ? <h3 className={styles['title']}>{title}</h3> : null}
        {body ? <p className={styles['body']}>{body}</p> : null}
      </div>
      {status.kind === 'declined' || position.index < position.total - 1 ? null : (
        <footer className={styles['foot']}>
          <IconShield size={18} />
          <p>
            {position.total > 1
              ? 'Nothing else will be written. If any of these tickets changes, your approval no longer applies.'
              : 'Nothing else will be written. If this ticket changes, your approval no longer applies.'}
          </p>
        </footer>
      )}
    </article>
  )
}
