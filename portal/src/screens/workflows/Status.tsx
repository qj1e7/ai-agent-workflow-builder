import { useState } from 'react'
import type { RunView, UseCaseView } from '../../api/types'
import { AgentFace } from '../../ui/AgentFace'
import { IconCheck, IconLock, IconPause, IconX } from '../../ui/icons'
import { faceStates, lifeWords, type AgentLink, type RunFact } from './workflow'
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

export function StatusPills({ state, fact }: { state: UseCaseView['state']; fact: RunFact | null }) {
  const changes = useChanges(state)
  const LifeIcon = state === 'paused' ? IconPause : IconCheck
  const RunIcon = fact ? RUN_ICON[fact.tone] : null
  return (
    <span className={styles['pills']}>
      <span key={changes} className={changes > 0 ? `${styles['pill']} ${styles['changed']}` : styles['pill']} data-life={state}>
        <LifeIcon size={12} />
        {lifeWords(state)}
      </span>
      {fact?.pill ? (
        <span className={styles['pill']} data-tone={fact.tone}>
          {RunIcon ? <RunIcon size={12} /> : null}
          {fact.pill}
        </span>
      ) : null}
    </span>
  )
}

export function Faces({ agents, useCase, latest }: { agents: readonly AgentLink[]; useCase: Pick<UseCaseView, 'state'>; latest: RunView | null }) {
  const states = faceStates(useCase, latest, agents.length)
  return (
    <span className={styles['faces']}>
      {agents.map((agent, index) => (
        <AgentFace key={agent.to} id={agent.face} display={agent.name} size={26} state={states[index] ?? 'idle'} />
      ))}
    </span>
  )
}
