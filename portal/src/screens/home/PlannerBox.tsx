import { useEffect, useRef, type KeyboardEvent, type RefObject } from 'react'
import { IconSend } from '../../ui/icons'
import styles from './Planner.module.css'

interface PlannerBoxProps {
  readonly text: string
  readonly busy: boolean
  readonly empty: boolean
  readonly phone: boolean
  readonly problem: string | null
  readonly boxRef: RefObject<HTMLTextAreaElement | null>
  readonly onChange: (text: string) => void
  readonly onSend: () => void
}

function placeholderOf(busy: boolean, empty: boolean, phone: boolean): string {
  if (busy) return 'The Planner is answering'
  if (!empty) return 'Ask for something else'
  return phone ? 'Ask about your software versions' : 'Ask about your software versions, or name software to watch'
}

/** The Planner's box. Enter sends, Shift+Enter starts a new line, and the box grows with the text. */
export function PlannerBox({ text, busy, empty, phone, problem, boxRef, onChange, onSend }: PlannerBoxProps) {
  const grown = useRef(0)
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    box.style.height = 'auto'
    grown.current = Math.min(box.scrollHeight, 160)
    box.style.height = `${grown.current}px`
  }, [text, boxRef])
  const ready = text.trim() !== '' && !busy
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (ready) onSend()
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (ready) onSend()
      }}
    >
      <div className={styles['composer']}>
        <label className="visually-hidden" htmlFor="planner-box">
          Ask the Planner about software versions
        </label>
        <textarea
          id="planner-box"
          ref={boxRef}
          rows={1}
          value={text}
          disabled={busy}
          maxLength={2000}
          placeholder={placeholderOf(busy, empty, phone)}
          enterKeyHint="send"
          aria-describedby={problem ? 'planner-problem' : undefined}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className={styles['send']} aria-label="Send to the Planner" aria-disabled={!ready || undefined}>
          <IconSend size={20} />
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
