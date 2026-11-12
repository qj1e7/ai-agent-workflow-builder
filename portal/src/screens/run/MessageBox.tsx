import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Button } from '../../ui/Button'
import { IconAlert } from '../../ui/icons'
import styles from './panels.module.css'

interface MessageBoxProps {
  readonly label: string
  readonly help: string
  /** What an empty send says, next to the box, which keeps focus. */
  readonly empty: string
  readonly send: string
  readonly pending: boolean
  readonly error: string | null
  readonly onSend: (text: string) => void
  /** Only a box that opened in place of other buttons has Cancel, and it takes focus when it opens. */
  readonly onCancel?: () => void
}

/** A question or its answer: one box, its help, and the words an empty send gets. */
export function MessageBox({ label, help, empty, send, pending, error, onSend, onCancel }: MessageBoxProps) {
  const id = useId()
  const field = useRef<HTMLTextAreaElement>(null)
  const [text, setText] = useState('')
  const [blank, setBlank] = useState(false)
  const opened = onCancel !== undefined
  useEffect(() => {
    if (opened) field.current?.focus()
  }, [opened])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (text.trim() === '') {
      setBlank(true)
      field.current?.focus()
      return
    }
    onSend(text.trim())
  }
  return (
    <form className={styles['askbox']} onSubmit={submit} noValidate>
      <div className={styles['field']}>
        <label htmlFor={id}>{label}</label>
        <textarea
          id={id}
          ref={field}
          rows={2}
          maxLength={1000}
          value={text}
          aria-invalid={blank ? true : undefined}
          aria-describedby={blank ? `${id}-help ${id}-err` : `${id}-help`}
          onChange={(event) => {
            setText(event.target.value)
            setBlank(false)
          }}
        />
        <span id={`${id}-help`} className={styles['help']}>
          {help}
        </span>
        {blank ? (
          <span id={`${id}-err`} className={styles['fieldError']}>
            <IconAlert size={16} />
            {empty}
          </span>
        ) : null}
      </div>
      <div className={styles['buttons']}>
        <Button type="submit" variant="primary" loading={pending}>
          {send}
        </Button>
        {onCancel ? (
          <Button disabled={pending} onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
      {error ? (
        <p className={styles['error']} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  )
}
