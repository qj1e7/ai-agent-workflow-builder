import { useEffect, useReducer, useRef, useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useMe, useRemoveSoftware, useRestoreSoftware, useStartRun, useWatchlist } from '../../api/queries'
import type { WatchedSoftwareView } from '../../api/types'
import { Button } from '../../ui/Button'
import { useChatNavigate } from '../../ui/fromChat'
import { OpenButton } from '../../ui/OpenItem'
import { pressCheckNow } from '../software/checkNow'
import { changeFeedback, noticeWords, NO_FEEDBACK, pressRemove, pressUndo } from '../software/removal'
import { scheduleRuns } from '../software/software'
import styles from './Planner.module.css'

interface StopProps {
  readonly row: WatchedSoftwareView
  readonly confirming: boolean
  readonly busy: boolean
  readonly ask: () => void
  readonly keep: () => void
  readonly stop: () => void
}

/** Stop watching sits last and asks first. The Software page’s own remove runs after the yes, and its Undo comes back. */
function StopWatching({ row, confirming, busy, ask, keep, stop }: StopProps) {
  const keepButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (confirming) keepButton.current?.focus()
  }, [confirming])
  if (!confirming) {
    return (
      <Button loading={busy} onClick={ask}>
        Stop watching<span className="visually-hidden"> {row.name}</span>
      </Button>
    )
  }
  return (
    <span className={styles['confirm']} role="group" aria-label={`Stop watching ${row.name}`}>
      <span>Stop watching {row.name}? It won’t be checked any more.</span>
      <Button ref={keepButton} onClick={keep}>
        Keep it<span className="visually-hidden"> on the watchlist</span>
      </Button>
      <Button variant="danger-outline" loading={busy} onClick={stop}>
        Yes, stop watching<span className="visually-hidden"> {row.name}</span>
      </Button>
    </span>
  )
}

function CheckAllNow({ useCaseId }: { useCaseId: string }) {
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useChatNavigate()
  const words = useErrorWords()
  return (
    <>
      <div className={styles['buttons']}>
        <Button loading={start.isPending} onClick={() => pressCheckNow(latch, start.mutate, useCaseId, (runId) => navigate(`/runs/${runId}`))}>
          Check all software now
        </Button>
      </div>
      {start.isError ? (
        <p className={styles['problem']} role="alert">
          {words(start.error)}
        </p>
      ) : null}
    </>
  )
}

/**
 * What an Operator can do with the software a question answer is about, using the Software page’s own calls: open its row,
 * check the watchlist now, and stop watching it. An Approver sees nothing here, as on the Software page. A name the
 * watchlist no longer holds gets no action.
 */
/** `named`: each row says its software's name. Leave it off when the card's title already names the one software. */
export function SoftwareActions({ names, named = true }: { names: readonly string[]; named?: boolean }) {
  const me = useMe()
  const watchlist = useWatchlist()
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const words = useErrorWords()
  const changes = useLatch()
  const [feedback, dispatch] = useReducer(changeFeedback, NO_FEEDBACK)
  const [confirming, setConfirming] = useState<string | null>(null)
  const view = watchlist.data
  const operator = me.data?.roles.includes('operator') === true
  if (!operator || view == null) return null

  const held = names.flatMap((name) => view.software.find((row) => row.name.toLowerCase() === name.toLowerCase()) ?? [])
  const { notice } = feedback
  if (held.length === 0 && notice === null) return null
  const paused = view.state === 'paused'
  const checking = { scheduled: scheduleRuns(view.schedule), paused }

  return (
    <div className={styles['actions']}>
      {held.length > 0 ? (
        <ul>
          {held.map((row) => (
            <li key={row.id}>
              {named ? <b>{row.name}</b> : null}
              <OpenButton item={{ kind: 'software', id: row.id }} to={`/software?row=${encodeURIComponent(row.id)}`}>
                Open<span className="visually-hidden"> {row.name}</span> on the Software page
              </OpenButton>
              <StopWatching
                row={row}
                confirming={confirming === row.id}
                busy={feedback.busy?.id === row.id && feedback.busy.act === 'remove'}
                ask={() => setConfirming(row.id)}
                keep={() => setConfirming(null)}
                stop={() => {
                  setConfirming(null)
                  pressRemove(changes, removal.mutate, row, dispatch, words)
                }}
              />
            </li>
          ))}
        </ul>
      ) : null}
      {held.length > 0 && !paused && view.software.length > 0 ? <CheckAllNow useCaseId={view.use_case_id} /> : null}
      <p role="status">{notice !== null ? noticeWords(notice, checking) : ''}</p>
      {notice?.kind === 'removed' ? (
        <div className={styles['buttons']}>
          <Button loading={feedback.busy?.act === 'restore'} onClick={() => pressUndo(changes, restore.mutate, notice.row, dispatch, words)}>
            Undo
          </Button>
          <Button onClick={() => dispatch({ type: 'dismissed' })}>Dismiss</Button>
        </div>
      ) : null}
      {feedback.problem !== null ? (
        <p className={styles['problem']} role="alert">
          {feedback.problem}
        </p>
      ) : null}
    </div>
  )
}
