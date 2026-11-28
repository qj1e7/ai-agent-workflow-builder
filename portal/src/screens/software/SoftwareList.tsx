import type { ReactNode } from 'react'
import type { WatchedSoftwareView } from '../../api/types'
import { cx } from '../../ui/cx'
import { Pill } from '../../ui/Pill'
import { newestOf, oursOf, rowNote, stateOf, watchRank } from './software'
import styles from './Software.module.css'

interface ListProps {
  readonly rows: readonly WatchedSoftwareView[]
  readonly checkedBy: string | null
  readonly label: string
  readonly now: Date
  /** The page draws the list on a surface of its own. In a card it is left flush, so a card holds no box inside it. */
  readonly surface?: boolean
  /** Draws the row's one link (or button), with the classes and cells to put in it. The page links to the software, the chat opens it beside itself. */
  readonly open: (row: WatchedSoftwareView, className: string, cells: ReactNode) => ReactNode
}

/**
 * The one list of watched software, on the watchlist's page and in the chat's panel and cards, so both say the same words in the same order:
 * its name and what checks it, the version you run, the newest, and its pill, each in a column that lines up on every row. Urgent first.
 * The two headings are drawn once, for the eye. Each cell names itself for a screen reader, and on a narrow list for everyone.
 */
export function SoftwareList({ rows, checkedBy, label, now, surface = false, open }: ListProps) {
  if (rows.length === 0) return null
  const sorted = [...rows].sort((a, b) => watchRank(a) - watchRank(b))
  return (
    <div className={cx(styles['table'], surface && styles['surface'])}>
      <div className={styles['cols']} aria-hidden="true">
        <span>You run</span>
        <span>Newest</span>
      </div>
      <ul className={styles['list']} aria-label={label}>
        {sorted.map((row) => {
          const state = stateOf(row)
          const cells = (
            <>
              <span className={styles['who']}>
                <b>{row.name}</b>
                <span className={styles['src']}>{rowNote(row, now, checkedBy)}</span>
              </span>
              <span className={styles['ver']} data-col="ours">
                <span className={styles['cellLabel']}>You run</span>{' '}
                {oursOf(row).version}
              </span>
              <span className={styles['ver']} data-col="newest">
                <span className={styles['cellLabel']}>Newest</span>{' '}
                {newestOf(row).version}
              </span>
              <Pill tone={state.tone}>{state.words}</Pill>
            </>
          )
          return (
            <li key={row.id} data-status={row.status} data-software-id={row.id}>
              {open(row, styles['rowLink'] ?? '', cells)}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
