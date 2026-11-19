import { useEffect, useRef, type KeyboardEvent, type RefObject } from 'react'
import { cx } from '../../ui/cx'
import { CHANGE_PLACEHOLDER, changingWords } from '../drafted/drafted'
import styles from './Planner.module.css'

interface PlannerBoxProps {
  readonly text: string
  readonly busy: boolean
  /** Before the first message the box is the hero's, taller, as in the sketch. */
  readonly empty: boolean
  readonly problem: string | null
  readonly boxRef: RefObject<HTMLTextAreaElement | null>
  readonly onChange: (text: string) => void
  readonly onSend: () => void
  /** Set while the next message changes a drafted workflow. The box says so, and Cancel goes back to the Planner. */
  readonly changing?: { readonly name: string; readonly revision: number; readonly onCancel: () => void } | null
}

/** The sketch's words, the same for everyone and before and after the first message. */
export const BOX_WORDS = 'Ask, or describe a task'

/** The Planner's box. Enter sends, Shift+Enter starts a new line, and the box grows with the text. */
export function PlannerBox({ text, busy, empty, problem, boxRef, onChange, onSend, changing = null }: PlannerBoxProps) {
  const grown = useRef(0)
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    box.style.height = 'auto'
    grown.current = Math.min(box.scrollHeight, 160)
    box.style.height = `${grown.current}px`
  }, [text, boxRef])
  const ready = text.trim() !== '' && !busy
  // Send stays black, as in the sketch. With nothing typed it takes them to the box, so it never does nothing.
  const send = () => (ready ? onSend() : boxRef.current?.focus())
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (ready) onSend()
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
    >
      {changing ? (
        <p className={styles['changing']} role="status">
          <span>{changingWords(changing.name, changing.revision)}</span>
          <button type="button" className={styles['linkButton']} onClick={changing.onCancel}>
            Cancel
          </button>
        </p>
      ) : null}
      <div className={cx(styles['composer'], empty && styles['fresh'])}>
        <label className="visually-hidden" htmlFor="planner-box">
          {BOX_WORDS}
        </label>
        <textarea
          id="planner-box"
          ref={boxRef}
          rows={1}
          value={text}
          readOnly={busy}
          aria-busy={busy || undefined}
          maxLength={2000}
          placeholder={changing ? CHANGE_PLACEHOLDER : BOX_WORDS}
          enterKeyHint="send"
          aria-describedby={problem ? 'planner-problem' : undefined}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className={styles['send']} aria-label="Send" aria-disabled={busy || undefined}>
          <svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true" focusable="false">
            <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      {problem ? (
        <p id="planner-problem" className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </form>
  )
}
