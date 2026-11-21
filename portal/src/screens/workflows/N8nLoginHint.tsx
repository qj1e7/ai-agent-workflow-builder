import type { ReactNode } from 'react'
import { useMe } from '../../api/queries'
import { opensInN8nAs } from './n8nHold'
import styles from './N8nLoginHint.module.css'

/**
 * An Open in n8n button with the n8n login it opens as under it. The Portal and n8n sign in separately, and the workflow moves
 * into this person's own n8n space, so the line names the account that can see it. Nothing is drawn under the button while the
 * platform does not know the login.
 */
export function WithN8nLogin({ children }: { children: ReactNode }) {
  const login = useMe().data?.n8n_login
  return (
    <div className={styles['wrap']}>
      {children}
      {login ? (
        <p className={styles['hint']} data-n8n-hint>
          {opensInN8nAs(login)}
        </p>
      ) : null}
    </div>
  )
}
