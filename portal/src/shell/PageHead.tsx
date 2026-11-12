import type { ReactNode } from 'react'
import styles from './PageHead.module.css'

export function PageHead({ heading, lead, movesFocus = false, children }: { heading: string; lead: ReactNode; movesFocus?: boolean; children?: ReactNode }) {
  return (
    <div className={styles['head']}>
      <div>
        <h1 tabIndex={-1} data-page-moves-focus={movesFocus || undefined}>
          {heading}
        </h1>
        <p>{lead}</p>
        {children}
      </div>
    </div>
  )
}

/** A short note under the page's lead, such as who may change the page. */
export function PageNote({ children }: { children: ReactNode }) {
  return <p className={styles['note']}>{children}</p>
}
