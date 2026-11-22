import { useState } from 'react'
import type { UseCaseView } from '../../api/types'
import { StatePill, type StateTone } from '../../ui/State'
import { runPill, STATE_TONE, type StageFacts } from '../run/words'
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

/** A workflow that is on is fine; paused and draft are grey, with a ring. */
const LIFE_TONE: Record<UseCaseView['state'], StateTone> = { on: 'on', paused: 'off', draft: 'off' }

/** One status, in the spec's words: Paused, else what the newest run needs, else On. A test run is marked beside it. */
export function StatusPills({ state, fact, test = false, large = false, fix = false }: { state: UseCaseView['state']; fact: Pill | null; test?: boolean; large?: boolean; fix?: boolean }) {
  // The sketch's wfState: Paused first, then Needs a fix whenever the version in use is not safe, then what the newest run needs.
  const unsafe = state === 'on' && fix
  const run = unsafe ? { tone: 'bad' as const, pill: 'Needs a fix' } : state === 'on' && fact?.pill ? fact : null
  const words = run?.pill ?? lifeWords(state)
  const changes = useChanges(words)
  return (
    <span className={large ? `${styles['pills']} ${styles['largePills']}` : styles['pills']}>
      <StatePill key={changes} tone={run ? STATE_TONE[run.tone] : LIFE_TONE[state]} className={changes > 0 ? styles['changed'] : undefined} data-life={state}>
        {words}
      </StatePill>
      {test ? <span className={styles['pill']}>Test run</span> : null}
    </span>
  )
}

/** A run's one pill: Stopped, Running, Waiting for a yes, Done, Nothing new or Declined. */
export function RunPill({ facts }: { facts: StageFacts }) {
  const { label, tone } = runPill(facts)
  return <StatePill tone={STATE_TONE[tone]}>{label}</StatePill>
}
