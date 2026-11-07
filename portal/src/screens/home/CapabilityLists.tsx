import type { CapabilitiesView } from '../../api/types'
import { capabilityGroups, stateWords, whyNot } from './answers'
import styles from './Planner.module.css'

/**
 * What the Planner can do, and what it can't do yet, straight from the platform's registry. Every entry's state is the platform's.
 * `folded` puts the second list behind one question, as day one does.
 */
export function CapabilityLists({ view, folded = false }: { view: CapabilitiesView; folded?: boolean }) {
  const { can, setup, notYet } = capabilityGroups(view)
  const left = [...setup, ...notYet]
  const leftList = (
    <ul>
      {left.map((entry) => (
        <li key={entry.id}>
          {entry.plain}
          <span className={styles['why']}>
            {stateWords(entry)}
            {whyNot(entry) === '' ? '' : `. ${whyNot(entry)}`}
          </span>
        </li>
      ))}
    </ul>
  )
  return (
    <div className={styles['abilities']}>
      <div>
        <h3>I can</h3>
        <ul>
          {can.map((entry) => (
            <li key={entry.id}>{entry.plain}</li>
          ))}
        </ul>
      </div>
      {folded ? null : (
        <div>
          <h3>Not yet</h3>
          {left.length > 0 ? leftList : <p className="muted">Nothing is waiting on setup.</p>}
        </div>
      )}
      {folded ? (
        <details>
          <summary>What can’t I do yet?</summary>
          {leftList}
        </details>
      ) : null}
    </div>
  )
}
