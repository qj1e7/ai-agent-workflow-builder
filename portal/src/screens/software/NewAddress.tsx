import { useEffect, useRef } from 'react'
import type { WatchedSoftwareView } from '../../api/types'
import { Button } from '../../ui/Button'
import { askNewAddressWords, movedWords, NEW_ADDRESS_ASK, notFoundWords } from './software'
import styles from './Software.module.css'

export const askButtonId = (id: string) => `new-address-${id}`

export const questionId = (id: string) => `new-address-question-${id}`

interface MovedProps {
  readonly row: WatchedSoftwareView
  readonly operator: boolean
  readonly confirming: boolean
  readonly busy: boolean
  readonly onAsk: () => void
  readonly onConfirm: () => void
  readonly onCancel: () => void
}

/** GitHub renamed the saved repository. An Operator may switch to the new name, after one confirmation. */
export function MovedNote({ row, operator, confirming, busy, onAsk, onConfirm, onCancel }: MovedProps) {
  const question = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (confirming) question.current?.focus()
  }, [confirming])
  useEffect(() => {
    if (!confirming || busy) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault()
        onCancel()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [confirming, busy, onCancel])
  if (!row.moved_to) return null
  if (!operator) {
    return (
      <div className={styles['moved']}>
        <span className={styles['src']}>{movedWords(row)}</span>
        <span className={styles['src']}>An Operator can switch it to the new address.</span>
      </div>
    )
  }
  if (confirming) {
    return (
      <div
        role="group"
        aria-labelledby={questionId(row.id)}
        className={styles['moved']}
      >
        <p ref={question} id={questionId(row.id)} tabIndex={-1} className={styles['question']}>
          {askNewAddressWords(row)}
        </p>
        <div className={styles['actions']}>
          <Button variant="primary" loading={busy} onClick={onConfirm}>
            Yes, use {row.moved_to}
          </Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    )
  }
  return (
    <div className={styles['moved']}>
      <span className={styles['src']}>{movedWords(row)}</span>
      <Button id={askButtonId(row.id)} onClick={onAsk}>
        {NEW_ADDRESS_ASK}
        <span className="visually-hidden"> for {row.name}</span>
      </Button>
    </div>
  )
}

interface NotFoundProps {
  readonly row: WatchedSoftwareView
  readonly operator: boolean
  readonly scheduled: boolean
  readonly paused: boolean
}

/** GitHub says the saved repository does not exist and does not say where it went, so nothing is offered. */
export function NotFoundNote({ row, operator, scheduled, paused }: NotFoundProps) {
  if (!row.not_found) return null
  return <span className={styles['src']}>{notFoundWords(row, { operator, scheduled, paused })}</span>
}
