import { useId, useRef } from 'react'
import { Button } from '../ui/Button'
import { ChatIcon } from './icons'
import iconButton from './IconButton.module.css'
import styles from './TeamsPanel.module.css'

export const TEAMS_TITLE = 'Teams, practice copy'
export const TEAMS_EMPTY_WORDS = 'No messages yet. When a run needs a yes, its message shows here.'

export function TeamsButton() {
  const dialog = useRef<HTMLDialogElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  return (
    <>
      <button
        ref={button}
        type="button"
        className={iconButton['button']}
        aria-label={TEAMS_TITLE}
        title={TEAMS_TITLE}
        onClick={() => dialog.current?.showModal()}
      >
        <ChatIcon />
        <span className={iconButton['label']}>Teams</span>
      </button>
      <dialog ref={dialog} className={styles['dialog']} aria-labelledby={titleId} onClose={() => button.current?.focus()}>
        <h2 id={titleId}>{TEAMS_TITLE}</h2>
        <p>{TEAMS_EMPTY_WORDS}</p>
        <Button onClick={() => dialog.current?.close()}>Close</Button>
      </dialog>
    </>
  )
}
