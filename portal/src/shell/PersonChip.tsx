import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useSession } from '../api/context'
import { rolesLabel } from '../api/labels'
import type { Me } from '../api/types'
import type { OidcSession } from '../api/session'
import { Button } from '../ui/Button'
import { personTone } from '../ui/personTone'
import styles from './PersonChip.module.css'

export const SIGN_OUT_FAILED_WORDS = 'Sign-out did not finish. Try again.'

/** The open menu takes Escape for itself, so the page under it, such as the Software notice, keeps what it shows. */
export function menuTakesEscape(event: Pick<KeyboardEvent, 'key' | 'preventDefault'>, open: boolean): boolean {
  if (event.key !== 'Escape' || !open) return false
  event.preventDefault()
  return true
}

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

// Safari does not focus a button on click, so a press on "Sign out" blurs with no related target. Only a move to a real element elsewhere counts as leaving.
export function focusMovedOutside(root: Pick<Node, 'contains'> | null, next: EventTarget | null): boolean {
  return next !== null && !root?.contains(next as Node)
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
    if (!menuTakesEscape(event, open)) return
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
        if (focusMovedOutside(root.current, event.relatedTarget)) setOpen(false)
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
