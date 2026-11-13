import { useId, type ReactNode } from 'react'
import { cx } from './cx'
import styles from './Card.module.css'

interface CardProps {
  /** The bold title, which names the card for a screen reader. */
  readonly title: ReactNode
  /** A state pill or tag at the end of the title’s line. */
  readonly pill?: ReactNode
  readonly children?: ReactNode
  /** What happened, at the left of the foot, such as “Saved as version 3.” */
  readonly status?: ReactNode
  /** The card’s buttons, at the right of the foot. */
  readonly actions?: ReactNode
  /** A foot that lays itself out in place of status and actions: a button at the right that opens into a box across the card, such as Ask the team. */
  readonly foot?: ReactNode
}

/** The chrome every card in the chat shares (the sketch’s `.card`): a head, the body, and a foot only when there is something in it. */
export function Card({ title, pill, children, status, actions, foot }: CardProps) {
  const titleId = useId()
  return (
    <section className={styles['card']} aria-labelledby={titleId}>
      <div className={styles['head']}>
        <h3 id={titleId}>{title}</h3>
        {pill}
      </div>
      {children}
      {foot !== undefined ? <div className={cx(styles['foot'], styles['own'])}>{foot}</div> : null}
      {foot === undefined && (status !== undefined || actions !== undefined) ? (
        <div className={styles['foot']}>
          {status !== undefined ? <span className={styles['status']}>{status}</span> : null}
          {actions !== undefined ? <span className={styles['actions']}>{actions}</span> : null}
        </div>
      ) : null}
    </section>
  )
}
