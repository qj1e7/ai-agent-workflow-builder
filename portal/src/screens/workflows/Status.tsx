import { useState } from 'react'
import type { UseCaseView } from '../../api/types'
import { Pill } from '../../ui/Pill'
import { runPill, type StageFacts } from '../run/words'
import { statusOf } from './workflow'
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

/** One status, in the four words ADR 0053 allows: On, Paused, Draft or Needs you. A test run is marked beside it. */
export function StatusPills({ useCase, test = false, large = false }: { useCase: Pick<UseCaseView, 'state' | 'last_run'> & Partial<Pick<UseCaseView, 'needs_you'>>; test?: boolean; large?: boolean }) {
  const { four, label, tone } = statusOf(useCase)
  const changes = useChanges(label)
  const look = tone === 'wait' ? 'wait' : four === 'needs' ? 'bad' : four === 'on' ? 'on' : 'off'
  return (
    <span className={styles['pills']}>
      <Pill key={changes} large={large} tone={look} className={changes > 0 ? styles['changed'] : undefined} data-life={useCase.state}>
        {label}
      </Pill>
      {test ? <Pill>Test run</Pill> : null}
    </span>
  )
}

/** A run's one pill: Stopped, Running, Waiting for approval, Done, Nothing new or Declined. */
export function RunPill({ facts }: { facts: StageFacts }) {
  const { label, tone } = runPill(facts)
  return (
    <Pill tone={tone}>{label}</Pill>
  )
}
