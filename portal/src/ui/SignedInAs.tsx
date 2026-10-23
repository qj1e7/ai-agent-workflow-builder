import { useState } from 'react'
import { rolesLabel } from '../api/labels'
import { useMe } from '../api/queries'
import type { OidcSession } from '../api/session'
import { Avatar } from './Avatar'
import { Button } from './Button'
import styles from './SignedInAs.module.css'

export const SIGN_OUT_FAILED_WORDS = 'Sign-out did not finish. Try again.'

export function SignedInAs({ session }: { session: OidcSession }) {
  const me = useMe().data
  const [failed, setFailed] = useState(false)

  function signOut() {
    setFailed(false)
    session.signOut().catch(() => setFailed(true))
  }

  return (
    <div className={styles['signedIn']}>
      {me ? (
        <span className={styles['person']}>
          <Avatar kind="person" name={me.display} size={32} />
          <span className={styles['who']}>
            <span className="visually-hidden">Signed in as </span>
            <span className={styles['name']}>{me.display}</span>
            <span className={styles['role']}>{rolesLabel(me.roles) || 'No role'}</span>
          </span>
        </span>
      ) : null}
      <Button onClick={signOut}>Sign out</Button>
      {failed ? (
        <p className={styles['failed']} role="alert">
          {SIGN_OUT_FAILED_WORDS}
        </p>
      ) : null}
    </div>
  )
}
