import type { ReactNode } from 'react'
import { runStateLabel } from '../api/labels'
import type { RunState } from '../api/types'
import { IconAlert, IconCheck, IconClock, IconRing, IconWave, IconX, type Icon } from './icons'
import { cx } from './cx'
import styles from './StatusPill.module.css'

export type PillTone = 'neutral' | 'working' | 'waiting' | 'done' | 'failed'

interface PillProps {
  tone: PillTone
  icon: Icon
  children: ReactNode
}

export function Pill({ tone, icon: Leading, children }: PillProps) {
  return (
    <span className={cx(styles['pill'], styles[tone])}>
      <Leading size={16} />
      {children}
    </span>
  )
}

const presentation: Record<RunState, { tone: PillTone; icon: Icon }> = {
  pending: { tone: 'neutral', icon: IconRing },
  working: { tone: 'working', icon: IconWave },
  proposed: { tone: 'working', icon: IconWave },
  awaiting_approval: { tone: 'waiting', icon: IconClock },
  acting: { tone: 'working', icon: IconWave },
  succeeded: { tone: 'done', icon: IconCheck },
  rejected: { tone: 'neutral', icon: IconX },
  failed: { tone: 'failed', icon: IconAlert },
}

export function StatusPill({ state }: { state: RunState }) {
  const { tone, icon } = presentation[state]
  return (
    <Pill tone={tone} icon={icon}>
      {runStateLabel[state]}
    </Pill>
  )
}
