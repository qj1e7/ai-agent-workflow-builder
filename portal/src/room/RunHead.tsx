import type { ReactNode } from 'react'
import type { RunState } from '../api/types'
import { StatusPill } from '../ui/StatusPill'
import styles from './RunHead.module.css'

interface RunHeadProps {
  title: string
  lede: ReactNode
  state: RunState | undefined
  titleId?: string
}

export function RunHead({ title, lede, state, titleId }: RunHeadProps) {
  return (
    <header className={styles['head']}>
      <h1 id={titleId} className={styles['title']}>
        {title}
      </h1>
      <p className={styles['lede']}>{lede}</p>
      {state ? (
        <div className={styles['pill']}>
          <StatusPill state={state} />
        </div>
      ) : null}
    </header>
  )
}
