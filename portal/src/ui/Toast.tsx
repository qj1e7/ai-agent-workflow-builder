import { useEffect, useId, useRef, useState } from 'react'
import { IconX } from './icons'
import { motionAllowed } from './motion'
import { readMs, startToastClock, type Hold, type ToastClock } from './toastClock'
import styles from './Toast.module.css'

export interface ToastMessage {
  /** A new id shows the message afresh, with a new clock. */
  readonly id: number
  readonly text: string
  readonly undo?: { readonly busy: boolean; readonly onPress: () => void }
}

export const UNDO_ID = 'toast-undo'

interface ToastProps {
  readonly message: ToastMessage | null
  readonly onDismiss: () => void
  /** Where focus goes when the message leaves while focus is on it. */
  readonly focusAfter: () => HTMLElement | null
}

/**
 * A message at the bottom of the page. One with Undo has no time limit: it stays until the next message, Escape,
 * Dismiss or leaving the page. One without Undo leaves after its reading time, which waits while the pointer or focus
 * is on it and while the tab is hidden.
 */
export function Toast({ message, onDismiss, focusAfter }: ToastProps) {
  return (
    <div className={styles['dock']}>
      <p role="status" className="visually-hidden">
        {message?.text ?? ''}
      </p>
      {message ? <Card key={message.id} message={message} onDismiss={onDismiss} focusAfter={focusAfter} /> : null}
    </div>
  )
}

function useLatest<T>(value: T): { readonly current: T } {
  const latest = useRef(value)
  useEffect(() => {
    latest.current = value
  })
  return latest
}

function Card({ message, onDismiss, focusAfter }: { message: ToastMessage; onDismiss: () => void; focusAfter: () => HTMLElement | null }) {
  const card = useRef<HTMLDivElement>(null)
  const clock = useRef<ToastClock | null>(null)
  const textId = useId()
  const [leaving, setLeaving] = useState(false)
  const timed = message.undo === undefined

  const leave = () => {
    if (card.current?.contains(document.activeElement)) focusAfter()?.focus()
    if (motionAllowed()) setLeaving(true)
    else onDismiss()
  }
  const latestLeave = useLatest(leave)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.querySelector('dialog[open]')) latestLeave.current()
    }
    document.addEventListener('keydown', onKey)
    if (!timed) return () => document.removeEventListener('keydown', onKey)
    const started = startToastClock(readMs(message.text), () => latestLeave.current())
    clock.current = started
    const onVisibility = () => (document.hidden ? started.hold('hidden') : started.release('hidden'))
    onVisibility()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      started.stop()
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [timed, message.text, latestLeave])

  const hold = (reason: Hold, on: boolean) => (on ? clock.current?.hold(reason) : clock.current?.release(reason))

  return (
    <div
      ref={card}
      className={leaving ? `${styles['toast']} ${styles['leaving']}` : styles['toast']}
      onPointerEnter={() => hold('hover', true)}
      onPointerLeave={() => hold('hover', false)}
      onFocus={() => hold('focus', true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) hold('focus', false)
      }}
      onAnimationEnd={(event) => {
        if (leaving && event.target === event.currentTarget) onDismiss()
      }}
    >
      <span id={textId} aria-hidden="true">
        {message.text}
      </span>
      {message.undo ? (
        <>
          <button
            id={UNDO_ID}
            type="button"
            className={styles['action']}
            aria-describedby={textId}
            aria-disabled={message.undo.busy || undefined}
            aria-busy={message.undo.busy || undefined}
            onClick={() => {
              if (!message.undo?.busy) message.undo?.onPress()
            }}
          >
            Undo
          </button>
          <button type="button" className={styles['close']} aria-label="Dismiss" onClick={leave}>
            <IconX size={16} strokeWidth={3} />
          </button>
        </>
      ) : null}
    </div>
  )
}
