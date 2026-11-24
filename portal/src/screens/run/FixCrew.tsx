import { AgentFace } from '../../ui/AgentFace'
import { agentIdentity } from '../../ui/agents'
import type { FixState } from './runModel'
import { fixWords } from './words'
import styles from './FixCrew.module.css'

/**
 * A fix on the stopped run, under the AI troubleshooter's words: where it stands, and each sub-agent it brought in as an Orb, in
 * the order it came. One that arrives while the page is open rises in. The log beside says each hand-off.
 */
export function FixCrew({ fix, loadedUpTo }: { fix: FixState; loadedUpTo: number }) {
  const face = fix.ended === 'proposed' ? 'success' : 'idle'
  return (
    <div className={styles['fix']}>
      <p className={styles['words']}>{fixWords(fix)}</p>
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
