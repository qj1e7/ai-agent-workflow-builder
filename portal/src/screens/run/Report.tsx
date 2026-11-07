import { useId, useState } from 'react'
import { Link } from 'react-router'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useReportToSupport } from '../../api/supportQueries'
import { Button } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import type { RunModel } from './runModel'
import { deliveryWords, FOLLOWING_UP_WORDS, NOTE_ROOM, reportNote } from './support'
import type { NameOf } from './words'
import styles from './panels.module.css'

interface ReportProps {
  readonly runId: string
  /** What the troubleshooter found, which the case carries. */
  readonly found: string
  readonly me: string | undefined
  readonly meName: string
  readonly reports: RunModel['reports']
  readonly nameOf: NameOf
}

/**
 * Report to support: one press makes a team request about this run. The page says it was sent when the platform kept
 * it, and says where the card went only as the platform reported it. The activity events tell the same story on a
 * later visit, so a report made earlier shows here with no button.
 */
export function ReportToSupport({ runId, found, me, meName, reports, nameOf }: ReportProps) {
  const noteId = useId()
  const helpId = useId()
  const [extra, setExtra] = useState('')
  const [key] = useState(newIdempotencyKey)
  const report = useReportToSupport()
  const latch = useLatch()
  const words = useErrorWords()
  const press = () =>
    latch.run((settled) => report.mutate({ runId, note: reportNote(found, extra, meName), idempotencyKey: key }, { onSettled: settled }))
  const sent = report.data
  const first = reports[0]
  if (sent || first) {
    const requestId = sent?.request_id ?? first?.requestId
    const byMe = sent !== undefined || first?.by === me
    return (
      <div className={styles['sentNote']} role="status">
        <span className={styles['okMark']}>
          <IconCheck size={18} />
        </span>
        <div>
          <b>{byMe ? 'You reported this to support.' : `${nameOf(first?.by ?? '')} reported this to support.`}</b>
          <p>
            {byMe ? FOLLOWING_UP_WORDS : `${nameOf(first?.by ?? '')} sees updates under Following up.`}
            {sent ? ` ${deliveryWords(sent)}` : ''}
          </p>
          {byMe && requestId ? <Link to={`/workflows?request=${encodeURIComponent(requestId)}`}>Open it under Following up</Link> : null}
        </div>
      </div>
    )
  }
  return (
    <div className={styles['report']}>
      <span>Report it. Support gets the run and this explanation, and you can follow the case under Following up on Workflows.</span>
      <label htmlFor={noteId}>
        Anything to add? <span className="muted">(optional)</span>
      </label>
      <textarea
        id={noteId}
        rows={3}
        maxLength={NOTE_ROOM}
        value={extra}
        aria-describedby={helpId}
        onChange={(event) => setExtra(event.target.value)}
      />
      <span id={helpId} className={styles['note']}>
        Support sees what the AI troubleshooter found and your note. Don’t paste passwords or keys.
      </span>
      <div className={styles['buttons']}>
        <Button variant="primary" loading={report.isPending} onClick={press}>
          Report to support
        </Button>
      </div>
      {report.isError ? (
        <p className={styles['error']} role="alert">
          Could not report this. {words(report.error)}
        </p>
      ) : null}
    </div>
  )
}
