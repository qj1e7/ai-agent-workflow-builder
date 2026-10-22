import { rolesLabel } from '../api/labels'
import { useMe } from '../api/queries'
import type { OidcSession } from '../api/session'
import { Avatar } from './Avatar'
import { Button } from './Button'
import styles from './SignedInAs.module.css'

/** The header's identity with real sign-in: the person's name, their roles in words, and the way out. */
export function SignedInAs({ session }: { session: OidcSession }) {
  const me = useMe().data
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
      <Button onClick={() => void session.signOut()}>Sign out</Button>
    </div>
  )
}
