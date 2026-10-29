import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useSession } from '../api/context'
import { rolesLabel } from '../api/labels'
import type { Me } from '../api/types'
import type { OidcSession } from '../api/session'
import { Button } from '../ui/Button'
import { personTone } from '../ui/personTone'
import styles from './PersonChip.module.css'

export const SIGN_OUT_FAILED_WORDS = 'Sign-out did not finish. Try again.'

function Who({ person }: { person: Me }) {
  const tone = personTone(person.display)
  return (
    <>
      <span className={styles['initial']} style={{ background: tone.bg, color: tone.ink }} aria-hidden="true">
        {person.display.charAt(0)}
      </span>
      <span>
        <span className={styles['name']}>{person.display}</span>
        <span className={styles['role']}>{rolesLabel(person.roles) || 'No role'}</span>
      </span>
    </>
  )
}

function titleOf(person: Me): string {
  return `${person.display}, ${rolesLabel(person.roles) || 'No role'}`
}

export function PersonChip({ person }: { person: Me }) {
  const session = useSession()
  if (session.kind === 'oidc') return <SignOutChip person={person} session={session} />
  return (
    <div className={styles['chip']} title={titleOf(person)}>
      <Who person={person} />
    </div>
  )
}

function SignOutChip({ person, session }: { person: Me; session: OidcSession }) {
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    function closeOnOutsidePress(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePress)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePress)
  }, [open])

  function onKeyDown(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !open) return
    setOpen(false)
    button.current?.focus()
  }

  function signOut() {
    setFailed(false)
    session.signOut().catch(() => setFailed(true))
  }

  return (
    <div
      ref={root}
      role="presentation"
      className={styles['root']}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        if (!root.current?.contains(event.relatedTarget)) setOpen(false)
      }}
    >
      <button
        ref={button}
        type="button"
        className={`${styles['chip']} ${styles['trigger']}`}
        title={titleOf(person)}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <Who person={person} />
      </button>
      {open ? (
        <div id={panelId} className={styles['panel']}>
          <Button onClick={signOut}>Sign out</Button>
          {failed ? (
            <p className={styles['failed']} role="alert">
              {SIGN_OUT_FAILED_WORDS}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
