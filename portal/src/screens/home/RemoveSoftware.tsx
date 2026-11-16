import { useEffect, useReducer, useRef } from 'react'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useMe, useRemoveSoftware, useRestoreSoftware } from '../../api/queries'
import type { ListedSoftware, RemoveSoftwareReply } from '../../api/types'
import { OperatorsNote } from '../../shell/OperatorsNote'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { cx } from '../../ui/cx'
import { IconCheck } from '../../ui/icons'
import { changeFeedback, isRemoval, NO_FEEDBACK, pressRemove, pressUndo, removalWords } from '../software/removal'
import styles from './Planner.module.css'

export const REMOVED = 'Removed from the watchlist.'

/** One watched software, with the Software page’s own Remove and Undo. */
function RemoveOne({ row, named }: { row: ListedSoftware; named: boolean }) {
  const removal = useRemoveSoftware()
  const restore = useRestoreSoftware()
  const words = useErrorWords()
  const changes = useLatch()
  const [feedback, dispatch] = useReducer(changeFeedback, NO_FEEDBACK)
  const undoButton = useRef<HTMLButtonElement>(null)
  const removeButton = useRef<HTMLButtonElement>(null)
  const item = { id: row.software_id, name: row.name }
  const { notice } = feedback
  useEffect(() => {
    if (notice?.kind === 'removed') undoButton.current?.focus()
    if (notice?.kind === 'restored') removeButton.current?.focus()
  }, [notice])

  const said = notice === null || !isRemoval(notice) ? '' : notice.kind === 'removed' ? REMOVED : removalWords(notice)
  return (
    <li>
      {named ? <b>{row.name}</b> : null}
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

/**
 * Software the Planner was asked to take off the Watchlist: each match with its Remove. Only an Operator removes, as on the
 * Software page; anyone else reads who can, and gets no button. A name the watchlist doesn’t hold is said in the sentence alone.
 */
export function RemoveSoftwareAnswer({ reply }: { reply: RemoveSoftwareReply }) {
  const me = useMe()
  const [only, ...others] = reply.matches
  if (only === undefined || me.data === undefined) return null
  if (!me.data.roles.includes('operator')) {
    return (
      <p className="muted">
        <OperatorsNote what="the watchlist" />
      </p>
    )
  }
  return (
    <Card title={others.length === 0 ? only.name : 'On your Watchlist'}>
      <div className={styles['actions']}>
        <ul>
          {reply.matches.map((row) => (
            <RemoveOne key={row.software_id} row={row} named={others.length > 0} />
          ))}
        </ul>
      </div>
    </Card>
  )
}
