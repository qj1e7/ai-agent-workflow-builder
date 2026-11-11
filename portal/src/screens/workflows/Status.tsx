import { useState } from 'react'
import type { UseCaseView } from '../../api/types'
import { IconCheck, IconLock, IconPause, IconX } from '../../ui/icons'
import { lifeWords, type Pill } from './workflow'
import styles from './Workflows.module.css'

export function useChanges(value: string): number {
  const [seen, setSeen] = useState(value)
  const [times, setTimes] = useState(0)
  if (seen !== value) {
    setSeen(value)
    setTimes(times + 1)
  }
  return times
}

const RUN_ICON = { wait: IconLock, bad: IconX, new: null, ok: null } as const

/** One status, in the spec's words: Paused, else what the newest run needs, else On. A test run is marked beside it. */
export function StatusPills({ state, fact, test = false }: { state: UseCaseView['state']; fact: Pill | null; test?: boolean }) {
  const run = state === 'on' && fact?.pill ? fact : null
  const words = run?.pill ?? lifeWords(state)
  const changes = useChanges(words)
  const Icon = run ? RUN_ICON[run.tone] : state === 'paused' ? IconPause : IconCheck
  return (
    <span className={styles['pills']}>
      <span key={changes} className={changes > 0 ? `${styles['pill']} ${styles['changed']}` : styles['pill']} data-life={state} data-tone={run?.tone}>
        {Icon ? <Icon size={12} /> : null}
        {words}
      </span>
      {test ? <span className={styles['pill']}>Test run</span> : null}
    </span>
  )
}
