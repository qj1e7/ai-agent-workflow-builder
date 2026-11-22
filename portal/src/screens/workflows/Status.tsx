import { useState } from 'react'
import type { UseCaseView } from '../../api/types'
import { IconCheck, IconLock, IconPause, IconX } from '../../ui/icons'
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

const ICON = { wait: IconLock, bad: IconX, new: null, ok: null } as const

/** One status, in the four words ADR 0053 allows: On, Paused, Draft or Needs you. A test run is marked beside it. */
export function StatusPills({ useCase, operator, test = false, large = false }: { useCase: Pick<UseCaseView, 'state' | 'last_run'> & Partial<Pick<UseCaseView, 'grade' | 'move_refused'>>; operator: boolean; test?: boolean; large?: boolean }) {
  const { four, label, tone } = statusOf(useCase, operator)
  const changes = useChanges(label)
  const Icon = four === 'needs' || tone === 'wait' ? ICON[tone ?? 'bad'] : four === 'paused' ? IconPause : four === 'draft' ? null : IconCheck
  return (
    <span className={large ? `${styles['pills']} ${styles['largePills']}` : styles['pills']}>
      <span key={changes} className={changes > 0 ? `${styles['pill']} ${styles['changed']}` : styles['pill']} data-life={useCase.state} data-tone={four === 'needs' || tone === 'wait' ? tone : undefined}>
        {Icon ? <Icon size={12} /> : null}
        {label}
      </span>
      {test ? <span className={styles['pill']}>Test run</span> : null}
    </span>
  )
}

/** A run's one pill: Stopped, Running, Waiting for a yes, Done, Nothing new or Declined. */
export function RunPill({ facts }: { facts: StageFacts }) {
  const { label, tone } = runPill(facts)
  return (
    <span className={styles['pill']} data-tone={tone}>
      {label}
    </span>
  )
}
