import { useEffect, useId, useRef, useState } from 'react'
import { Link } from '../../ui/Link'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useAskTheTeam } from '../../api/supportQueries'
import { Button } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { deliveryWords, FOLLOWING_UP_WORDS, NOTE_LIMIT } from '../run/support'
import { requestPath } from '../workflows/requests'
import { useMainButton } from './primary'
import styles from './Planner.module.css'

const CAPABILITY_ROOM = 80

interface AskTheTeamProps {
  /** What the request is about, in a few words: the system or ability. The platform keeps it with the request. */
  readonly capability: string
  /** What the note starts with. The person can change every word. */
  readonly starter: string
  readonly label?: string
  readonly secondary?: boolean
}

/**
 * Ask the team: the platform keeps the request and the team decides. It needs no AI model. The line after says the request
 * was saved, and says where its card went only as the platform reported it.
 */
export function AskTheTeam({ capability, starter, label = 'Ask the team', secondary = true }: AskTheTeamProps) {
  const main = useMainButton()
  const noteId = useId()
  const helpId = useId()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState(starter)
  const [key] = useState(newIdempotencyKey)
  const ask = useAskTheTeam()
  const field = useRef<HTMLTextAreaElement>(null)
  const opener = useRef<HTMLButtonElement>(null)
  const sentNote = useRef<HTMLDivElement>(null)
  const moved = useRef<'open' | 'close' | 'sent' | null>(null)
  const latch = useLatch()
  const words = useErrorWords()
  const sent = ask.data
  // The control the person used is replaced by what it opened, so focus follows it.
  useEffect(() => {
    const to = moved.current
    if (to === 'sent' && !sent) return
    moved.current = null
    if (to === 'open') field.current?.focus()
    if (to === 'close') opener.current?.focus()
    if (to === 'sent') sentNote.current?.focus()
  })
  if (sent) {
    return (
      <div className={styles['sent']} role="status" tabIndex={-1} ref={sentNote}>
        <IconCheck size={18} />
        <div>
          <b>Saved as a request for the team.</b>
          <p>
            {FOLLOWING_UP_WORDS} {deliveryWords(sent)}
          </p>
          <Link to={requestPath(sent.request_id)}>Open it under Following up</Link>
        </div>
      </div>
    )
  }
  if (!open) {
    return (
      <Button
        ref={opener}
        variant={secondary ? 'secondary' : main}
        onClick={() => {
          moved.current = 'open'
          setOpen(true)
        }}
      >
        {label}
      </Button>
    )
  }
  const press = () => {
    moved.current = 'sent'
    latch.run((settled) =>
      ask.mutate({ capability: capability.trim().slice(0, CAPABILITY_ROOM) || 'something new', note: note.trim().slice(0, NOTE_LIMIT), idempotencyKey: key }, { onSettled: settled }),
    )
  }
  return (
    <div className={styles['ask']}>
      <label htmlFor={noteId}>What should the team know?</label>
      <textarea id={noteId} ref={field} value={note} maxLength={NOTE_LIMIT} aria-describedby={helpId} onChange={(event) => setNote(event.target.value)} />
      <span id={helpId} className={styles['note']}>
        The team sees this and decides. Don’t paste passwords or keys.
      </span>
      <div className={styles['buttons']}>
        <Button loading={ask.isPending} disabled={note.trim() === ''} onClick={press}>
          Save the request
        </Button>
        <Button
          onClick={() => {
            moved.current = 'close'
            setOpen(false)
          }}
        >
          Never mind
        </Button>
      </div>
      {ask.isError ? (
        <p className={styles['problem']} role="alert">
          Could not save this. {words(ask.error)}
        </p>
      ) : null}
    </div>
  )
}
