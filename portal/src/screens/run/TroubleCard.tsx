import type { CSSProperties, ReactNode } from 'react'
import { AgentFace, type FaceState } from '../../ui/AgentFace'
import styles from './TroubleCard.module.css'

/**
 * The AI troubleshooter's card under a stop, as the sketch's `.fix`: its face, its name, then its answers and the next step. The mood
 * follows the run, and a fix while one runs. When the stage is drawn, a notch on the card points at the step that stopped: `at` is that
 * step's column as a share of the stage's width.
 */
export function TroubleCard({ face, at, children }: { face: FaceState; at: number | null; children: ReactNode }) {
  return (
    <div className={styles['card']} style={at === null ? undefined : ({ '--at': at } as CSSProperties)}>
      {at === null ? null : <span className={styles['notch']} data-notch aria-hidden="true" />}
      <AgentFace id="troubleshooter" size={52} state={face} />
      <div className={styles['body']}>
        <p className={styles['who']}>AI troubleshooter</p>
        {children}
      </div>
    </div>
  )
}
