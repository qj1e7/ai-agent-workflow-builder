import { useEffect, useId, useRef, useState } from 'react'
import type { Pager } from '../api/homeQueries'
import { Button } from './Button'
import styles from './ShowMore.module.css'

/** The line under a list that is longer than what it shows, read out each time it changes. */
export function shownWords(shown: number, total: number, failed = false): string {
  if (failed) return `Showing ${String(shown)} of ${String(total)}. I couldn’t read more just now. Try again.`
  return shown < total ? `Showing ${String(shown)} of ${String(total)}.` : `Showing all ${String(total)}.`
}

/**
 * Where focus goes after a press of Show more, given the rows drawn when it was pressed and the rows drawn now. `waiting` until
 * the read lands. `kept` when new rows came and the button is still there, so focus stays on it. Once the last rows arrive the
 * button goes, and focus moves to the first new row in drawn order, or to the line when no row is new.
 */
export type Landing = 'waiting' | 'kept' | 'line' | { readonly row: string }

export function landing(before: ReadonlySet<string>, keys: readonly string[], more: boolean, busy: boolean): Landing {
  if (busy) return 'waiting'
  const first = keys.find((key) => !before.has(key))
  if (more) return first === undefined ? 'waiting' : 'kept'
  return first === undefined ? 'line' : { row: first }
}

interface ShowMoreProps {
  readonly shown: number
  readonly total: number
  readonly pager: Pager
  /** The rows' keys in the order they are drawn. */
  readonly keys: readonly string[]
  /** The attribute that holds a row's key on the element around it, such as `data-home-item`. */
  readonly rowAttr: string
}

/**
 * Show more under a list the platform sends a page at a time (principles 7 and 9): the next rows join the same list, the line
 * above the button says how many show of how many, and a screen reader hears it change. Focus stays on the button while there
 * is more. When the last rows arrive the button goes, and focus moves to the first of them.
 */
export function ShowMore({ shown, total, pager, keys, rowAttr }: ShowMoreProps) {
  const lineId = useId()
  const line = useRef<HTMLParagraphElement>(null)
  const before = useRef<ReadonlySet<string> | null>(null)
  const [pressed, setPressed] = useState(false)
  const more = shown < total

  useEffect(() => {
    const was = before.current
    if (was === null) return
    const next = landing(was, keys, more, pager.busy)
    if (next === 'waiting') return
    before.current = null
    if (next === 'kept') return
    const row = next === 'line' ? null : line.current?.parentElement?.parentElement?.querySelector(`[${rowAttr}="${CSS.escape(next.row)}"]`)
    const target = row?.querySelector<HTMLElement>('a[href], button:not([aria-disabled="true"])') ?? line.current
    target?.focus()
  }, [keys, more, pager.busy, rowAttr])

  if (!more && !pressed) return null
  return (
    <div className={styles['more']}>
      <p id={lineId} ref={line} role="status" tabIndex={-1} className={more || pager.failed ? styles['note'] : 'visually-hidden'}>
        {shownWords(shown, total, pager.failed)}
      </p>
      {more ? (
        <Button
          aria-describedby={lineId}
          loading={pager.busy}
          onClick={() => {
            before.current = new Set(keys)
            setPressed(true)
            pager.showMore()
          }}
        >
          Show more
        </Button>
      ) : null}
    </div>
  )
}
