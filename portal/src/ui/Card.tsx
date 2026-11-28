import { useId, type ReactNode } from 'react'
import { cx } from './cx'
import styles from './Card.module.css'

/** A card is named by its bold title, or, when the words above it already say what it is, by a label a screen reader reads alone. */
type Named = { readonly title: ReactNode; readonly label?: never } | { readonly title?: never; readonly label: string }

type CardProps = Named & {
  /** A state pill or tag at the end of the title’s line. */
  readonly pill?: ReactNode
  readonly children?: ReactNode
  /** What happened, at the left of the foot, such as “Saved as version 3.” */
  readonly status?: ReactNode
  /** The card’s buttons, at the right of the foot. */
  readonly actions?: ReactNode
  /** A foot that lays itself out in place of status and actions: a button at the right that opens into a box across the card, such as Ask the team. */
  readonly foot?: ReactNode
  /** The title's id, for a card that moves focus to its title after a press. The title then takes focus from script only. */
  readonly headingId?: string
}

/** The chrome every card in the chat shares (the sketch’s `.card`): a head unless it is named by a label, the body, and a foot only when there is something in it. */
export function Card({ title, label, pill, children, status, actions, foot, headingId }: CardProps) {
  const ownId = useId()
  const titleId = headingId ?? ownId
  return (
    <section className={styles['card']} aria-labelledby={label === undefined ? titleId : undefined} aria-label={label}>
      {label === undefined ? (
        <div className={styles['head']}>
          <h3 id={titleId} tabIndex={headingId === undefined ? undefined : -1}>
            {title}
          </h3>
          {pill}
        </div>
      ) : null}
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

/** Dense words folded under a plain summary, closed until pressed: the browser's own disclosure keeps the keyboard and the screen reader's state. */
export function CardFold({ summary, children }: { readonly summary: string; readonly children: ReactNode }) {
  return (
    <details className={styles['fold']}>
      <summary>{summary}</summary>
      {children}
    </details>
  )
}
