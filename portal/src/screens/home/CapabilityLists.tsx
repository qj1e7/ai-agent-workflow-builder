import type { CapabilitiesView } from '../../api/types'
import { capabilityGroups, stateWords, whyNot } from './answers'
import styles from './Planner.module.css'

/** What the Planner can do for software versioning, straight from the platform's registry. Every entry's state is the platform's. */
export function CapabilityLists({ view }: { view: CapabilitiesView }) {
  const { can, setup } = capabilityGroups(view)
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
      {setup.length > 0 ? (
        <div>
          <h3>Needs setup</h3>
          <ul>
            {setup.map((entry) => (
              <li key={entry.id}>
                {entry.plain}
                <span className={styles['why']}>
                  {stateWords(entry)}
                  {whyNot(entry) === '' ? '' : `. ${whyNot(entry)}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
