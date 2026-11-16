import { useContext, useEffect, useReducer, useRef } from 'react'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useRemoveSoftware, useRestoreSoftware, useWatchlist } from '../../api/queries'
import type { ListedSoftware, RemoveSoftwareReply } from '../../api/types'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { cx } from '../../ui/cx'
import { IconCheck } from '../../ui/icons'
import { changeFeedback, isRemoval, NO_FEEDBACK, pressRemove, pressUndo, removalWords } from '../software/removal'
import { CardMemoryContext } from './cardMemory'
import styles from './Planner.module.css'

export const REMOVED = 'Removed from the watchlist.'

/** One watched software, with the Software page’s own Remove and Undo. Several rows name their source, since two can share a name. */
function RemoveOne({ row, several }: { row: ListedSoftware; several: boolean }) {
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const watchlist = useWatchlist()
  const words = useErrorWords()
  const changes = useLatch()
  const memory = useContext(CardMemoryContext)
  const [feedback, dispatch] = useReducer(changeFeedback, NO_FEEDBACK, (empty) => ({ ...empty, notice: memory.removals.kept()?.[row.software_id] ?? null }))
  const undoButton = useRef<HTMLButtonElement>(null)
  const removeButton = useRef<HTMLButtonElement>(null)
  const item = { id: row.software_id, name: row.name }
  const { notice } = feedback
  const shown = useRef(notice)
  useEffect(() => {
    if (notice === shown.current) return
    shown.current = notice
    memory.removals.keep({ ...memory.removals.kept(), [row.software_id]: notice })
    if (notice?.kind === 'removed') undoButton.current?.focus()
    if (notice?.kind === 'restored') removeButton.current?.focus()
  }, [notice, memory, row.software_id])

  const source = several ? watchlist.data?.software.find((entry) => entry.id === row.software_id)?.source.ref : undefined
  const said = notice === null || !isRemoval(notice) ? '' : notice.kind === 'removed' ? REMOVED : removalWords(notice)
  return (
    <li>
      {several ? <b>{row.name}</b> : null}
      {source ? <span className="muted">{source}</span> : null}
      <span className={cx(styles['cardDone'], notice?.kind === 'removed' && styles['cardOk'])} role="status">
        {notice?.kind === 'removed' ? <IconCheck size={15} /> : null}
        {said}
      </span>
      {notice?.kind === 'removed' ? (
        <Button ref={undoButton} loading={feedback.busy?.act === 'restore'} onClick={() => pressUndo(changes, restore.mutate, item, dispatch, words)}>
          Undo<span className="visually-hidden"> removing {row.name}</span>
        </Button>
      ) : notice?.kind === 'gone' ? null : (
        <Button ref={removeButton} variant="danger-outline" loading={feedback.busy?.act === 'remove'} onClick={() => pressRemove(changes, removal.mutate, item, dispatch, words)}>
          Remove from watchlist<span className="visually-hidden"> {row.name}</span>
        </Button>
      )}
      {feedback.problem !== null ? (
        <p className={styles['problem']} role="alert">
          {feedback.problem}
        </p>
      ) : null}
    </li>
  )
}

/** Software the Planner was asked to take off the Watchlist: each match with its Remove. A name it doesn’t hold is said in the sentence alone. */
export function RemoveSoftwareAnswer({ reply }: { reply: RemoveSoftwareReply }) {
  const [only, ...others] = reply.matches
  if (only === undefined) return null
  return (
    <Card title={others.length === 0 ? only.name : 'On your Watchlist'}>
      <div className={styles['actions']}>
        <ul>
          {reply.matches.map((row) => (
            <RemoveOne key={row.software_id} row={row} several={others.length > 0} />
          ))}
        </ul>
      </div>
    </Card>
  )
}
