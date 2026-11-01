import type { WatchedSoftwareView } from '../../api/types'
import { TicketKeys } from '../jira/TicketKeys'
import { historyOf, ticketsOf } from './software'
import styles from './Software.module.css'

export function SoftwareHistory({ row, nameOf, id }: { row: WatchedSoftwareView; nameOf: (id: string) => string; id: string }) {
  return (
    <div className={styles['history']} id={id}>
      <ol className={styles['timeline']} aria-label={`History of ${row.name}`}>
        {historyOf(row, nameOf).map((line, index) => (
          <li key={index}>
            <b>{line.when}</b>
            <span>
              <TicketKeys text={line.words} keys={ticketsOf(row)} />
            </span>
          </li>
        ))}
      </ol>
      <p className="muted">This shows the latest facts. Earlier checks are not kept yet.</p>
    </div>
  )
}
