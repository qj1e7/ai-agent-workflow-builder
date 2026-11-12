import { useEffect, useRef, type KeyboardEvent, type RefObject } from 'react'
import { IconSend } from '../../ui/icons'
import type { Asker } from './answers'
import styles from './Planner.module.css'

interface PlannerBoxProps {
  readonly text: string
  readonly busy: boolean
  readonly empty: boolean
  readonly phone: boolean
  readonly asker: Asker
  readonly problem: string | null
  readonly boxRef: RefObject<HTMLTextAreaElement | null>
  readonly onChange: (text: string) => void
  readonly onSend: () => void
}

/** What the box offers before the first message: an Operator’s software, or the questions someone who isn’t an Operator can ask. */
const FIRST: Readonly<Record<Asker, { readonly wide: string; readonly phone: string; readonly label: string }>> = {
  operator: { wide: 'Ask about your software versions, or name software to watch', phone: 'Ask about your software versions', label: 'Ask the Planner about software versions' },
  approver: { wide: 'Ask about your approvals, or how the workflows are doing', phone: 'Ask about your approvals', label: 'Ask the Planner about your approvals and the workflows' },
}

function placeholderOf(busy: boolean, empty: boolean, phone: boolean, asker: Asker): string {
  if (busy) return 'The Planner is answering'
  if (!empty) return asker === 'operator' ? 'Ask for something else' : 'Ask something else'
  return phone ? FIRST[asker].phone : FIRST[asker].wide
}

/** The Planner's box. Enter sends, Shift+Enter starts a new line, and the box grows with the text. */
export function PlannerBox({ text, busy, empty, phone, asker, problem, boxRef, onChange, onSend }: PlannerBoxProps) {
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
          {FIRST[asker].label}
        </label>
        <textarea
          id="planner-box"
          ref={boxRef}
          rows={1}
          value={text}
          disabled={busy}
          maxLength={2000}
          placeholder={placeholderOf(busy, empty, phone, asker)}
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
