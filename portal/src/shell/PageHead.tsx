import type { ReactNode } from 'react'
import styles from './PageHead.module.css'

export function PageHead({ heading, lead, movesFocus = false, note, children }: { heading: string; lead: string; movesFocus?: boolean; note?: ReactNode; children?: ReactNode }) {
  return (
    <div className={styles['head']}>
      <div>
        <h1 tabIndex={-1} data-page-moves-focus={movesFocus || undefined}>
          {heading}
        </h1>
        <p>{lead}</p>
        {note ? <p className={styles['note']}>{note}</p> : null}
        {children}
      </div>
    </div>
  )
}
