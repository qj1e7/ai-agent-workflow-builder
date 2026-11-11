import { useId, useState } from 'react'
import { useCacheScope, useSession } from '../api/context'
import { useDevUsers } from '../api/queries'
import { SettingsIcon } from './icons'
import styles from './TestControls.module.css'

export const TEST_NOTE = 'Only on a practice stack. Real sign-in hides this.'

export function TestControls() {
  const session = useSession()
  if (session.kind !== 'dev') return null
  return <Panel choose={session.choose} />
}

function Panel({ choose }: { choose: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const current = useCacheScope()
  const users = useDevUsers().data
  const panelId = useId()
  return (
    <div className={styles['root']}>
      {open ? (
        <div id={panelId} className={styles['panel']} role="region" aria-label="Test controls">
          <p className={styles['title']}>Test controls</p>
          <p className={styles['note']}>{TEST_NOTE}</p>
          <div className={styles['row']}>
            <span>Act as</span>
            <span className={styles['segmented']}>
              {(users ?? []).map((user) => (
                <button key={user.id} type="button" aria-pressed={user.id === current} onClick={() => choose(user.id)}>
                  {user.display}
                </button>
              ))}
            </span>
          </div>
        </div>
      ) : null}
      <button
        type="button"
        className={styles['toggle']}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <SettingsIcon size={16} />
        {open ? 'Hide test controls' : 'Test controls'}
      </button>
    </div>
  )
}
