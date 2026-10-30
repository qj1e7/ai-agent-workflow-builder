import { matches } from './software'
import styles from './Software.module.css'

/** The count line is its own status region, so a screen reader hears only the count as the person types. */
export function FindSoftware({ query, shown, onChange }: { query: string; shown: number; onChange: (query: string) => void }) {
  return (
    <div className={styles['find']}>
      <label htmlFor="find-software">Find software</label>
      <input id="find-software" type="search" value={query} placeholder="Find software" autoComplete="off" onChange={(event) => onChange(event.target.value)} />
      <p className="visually-hidden" role="status">
        {query.trim() === '' ? '' : matches(shown)}
      </p>
    </div>
  )
}
