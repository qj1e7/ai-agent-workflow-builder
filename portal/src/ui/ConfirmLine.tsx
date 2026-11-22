import type { ReactNode } from 'react'
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
  return (
    <span className={styles['confirm']} role="group" aria-label={groupName}>
      <span>{question}</span>
      <Button ref={takeFocus} onClick={onKeep}>
        {keep}
      </Button>
      <Button variant="danger-outline" loading={busy} onClick={onYes}>
        {yes}
      </Button>
    </span>
  )
}
