import type { ReactNode } from 'react'
import { IconAlert, IconCheck, type Icon } from './icons'
import { cx } from './cx'
import styles from './Feedback.module.css'

export function Skeleton({ lines = 3, label }: { lines?: number; label: string }) {
  return (
    <div className={styles['skeleton']} role="status" aria-busy="true">
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} className={styles['bar']} aria-hidden="true" />
      ))}
    </div>
  )
}

interface InlineMessageProps {
  tone: 'error' | 'success'
  children: ReactNode
  id?: string
}

const toneIcon: Record<InlineMessageProps['tone'], Icon> = { error: IconAlert, success: IconCheck }

export function InlineMessage({ tone, children, id }: InlineMessageProps) {
  const Leading = toneIcon[tone]
  return (
    <p id={id} className={cx(styles['message'], styles[tone])} role={tone === 'error' ? 'alert' : 'status'}>
      <Leading size={18} />
      <span>{children}</span>
    </p>
  )
}

interface EmptyStateProps {
  title: string
  children: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <div className={styles['empty']}>
      <h2>{title}</h2>
      <p className="muted">{children}</p>
      {action ? <div className={styles['action']}>{action}</div> : null}
    </div>
  )
}
