import { useEffect, useState } from 'react'
import styles from './Planner.module.css'

/** After this long a pending answer says it is still working. A question about the person’s data makes a second call, so it takes longer. */
export const STILL_WORKING_MS = 8000
export const WORKING = 'Working on it…'
export const STILL_WORKING = 'Still working. Questions about your data take a little longer.'

/** The words for a pending answer that has taken this long. */
export const waitingWords = (elapsedMs: number): string => (elapsedMs >= STILL_WORKING_MS ? STILL_WORKING : WORKING)

/** What the Planner says while an answer is pending. No step is named, because none is known. The words are static, so reduced motion needs nothing. */
export function Waiting() {
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  useEffect(() => {
    const first = setTimeout(() => setElapsedMs(0), 0)
    const timer = setTimeout(() => setElapsedMs(STILL_WORKING_MS), STILL_WORKING_MS)
    return () => {
      clearTimeout(first)
      clearTimeout(timer)
    }
  }, [])
  // The status region mounts empty and gets its words after, so screen readers announce them.
  return (
    <p className={styles['waiting']} role="status">
      {elapsedMs === null ? '' : waitingWords(elapsedMs)}
    </p>
  )
}
