import { AgentFace } from '../../ui/AgentFace'
import { agentIdentity } from '../../ui/agents'
import { fixEnd, type FixState } from './runModel'
import { fixWords } from './words'
import styles from './FixCrew.module.css'

/**
 * A fix on the stopped run, under the AI troubleshooter's words: where it stands, and each sub-agent it brought in as an Orb, in
 * the order it came. One that arrives while the page is open rises in. The log beside says each hand-off. Once the fix's
 * twenty minutes are up with nothing to end it, it reads as handed back, as the platform counts it. `line` replaces the words with
 * the platform's own once it has answered, and `null` leaves them out when a card says them.
 */
export function FixCrew({ fix, now, loadedUpTo = Number.MAX_SAFE_INTEGER, line }: { fix: FixState; now: number; loadedUpTo?: number; line?: string | null }) {
  const face = fixEnd(fix, now) === 'proposed' ? 'success' : 'idle'
  const words = line === undefined ? fixWords(fix, now) : line
  return (
    <div className={styles['fix']}>
      {words === null ? null : <p className={styles['words']}>{words}</p>}
      {fix.agents.length > 0 ? (
        <ul className={styles['crew']} aria-label="Agents on the fix">
          {fix.agents.map(({ agent, seq }) => (
            <li key={agent.id} data-arrived={seq > loadedUpTo || undefined}>
              <AgentFace id={agent.id} display={agent.display} size={28} state={face} />
              <span style={{ color: agentIdentity(agent.id, agent.display).hue }}>{agent.display}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
