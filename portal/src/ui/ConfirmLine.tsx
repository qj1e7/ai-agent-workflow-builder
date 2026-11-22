import { useId, type KeyboardEvent, type ReactNode } from 'react'
import { Button } from './Button'
import styles from './ConfirmLine.module.css'

interface ConfirmLineProps {
  readonly groupName: string
  readonly question: ReactNode
  readonly keep: ReactNode
  readonly yes: ReactNode
  readonly busy?: boolean
  readonly onKeep: () => void
  readonly onYes: () => void
}

/** Stable, so React calls it once as the line opens, not on every draw. */
const takeFocus = (button: HTMLButtonElement | null) => button?.focus()

export function ConfirmLine({ groupName, question, keep, yes, busy = false, onKeep, onYes }: ConfirmLineProps) {
  const questionId = useId()
  const keepOnEscape = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    onKeep()
  }
  return (
    <span className={styles['confirm']} role="group" aria-label={groupName} aria-describedby={questionId}>
      <span id={questionId}>{question}</span>
      <Button ref={takeFocus} onClick={onKeep} onKeyDown={keepOnEscape}>
        {keep}
      </Button>
      <Button variant="danger-outline" loading={busy} onClick={onYes} onKeyDown={keepOnEscape}>
        {yes}
      </Button>
    </span>
  )
}
