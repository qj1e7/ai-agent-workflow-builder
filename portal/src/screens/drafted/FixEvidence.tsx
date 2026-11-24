import type { FixEvidenceView } from '../../api/types'
import styles from './Drafted.module.css'

type Fix = FixEvidenceView

const VERDICT: Readonly<Record<Fix['scenarios'][number]['verdict'], string>> = { passed: 'Passed', failed: 'Failed', not_tried: 'Not tried' }
export const CHECKS_ARE_CODES = 'These come from the platform’s own checks, never from an AI’s summary.'
export const NO_CHECKS = 'The platform has no checks to show for this fix.'

/** The coordinator's own replay of the stop has a name made for code. Say it in plain words. */
const SCENARIO_NAME: Readonly<Record<string, string>> = { replay_the_stop: 'Replay the stop' }

function ListHead({ children }: { children: string }) {
  return <h2 className={styles['kind']}>{children}</h2>
}

/**
 * What an Approver decides on for a fix, all of it the platform's own: the cause, the change from what it was to what it becomes,
 * each scenario and its verdict, and each check. Nothing here is the AI's summary, and the page says so.
 */
export function FixEvidence({ fix }: { fix: Fix }) {
  return (
    <>
      <section className={styles['more']} aria-label="The cause">
        <ListHead>The cause</ListHead>
        <p>{fix.cause ?? 'The platform could not confirm the cause.'}</p>
      </section>
      <section className={styles['more']} aria-label="What it changes">
        <ListHead>What it changes</ListHead>
        {fix.changes.length > 0 ? (
          <ul className={styles['rows']}>
            {fix.changes.map((change) => (
              <li key={`${change.block}:${change.parameter}`}>
                <b>{change.block}</b> <span className="muted">{change.parameter}</span> <s>{change.before ?? 'nothing'}</s> <span aria-hidden="true">→</span> <b>{change.after ?? 'nothing'}</b>
              </li>
            ))}
          </ul>
        ) : (
          <p>No value changed.</p>
        )}
        {fix.made_by === 'person' ? <p>{fix.answered_by ?? 'A person'} answered the question, and the platform made the change from the answer.</p> : null}
        {fix.read_list ? <p>{fix.read_list}</p> : null}
      </section>
      <section className={styles['more']} aria-label="Scenarios">
        <ListHead>Scenarios, on practice systems</ListHead>
        <ul className={styles['rows']}>
          {fix.scenarios.map((scenario) => (
            <li key={scenario.name}>
              <span>{SCENARIO_NAME[scenario.name] ?? scenario.name}</span> <b>{VERDICT[scenario.verdict]}</b>
              {scenario.why ? <span className="muted"> {scenario.why}</span> : null}
            </li>
          ))}
        </ul>
      </section>
      <section className={styles['more']} aria-label="What the platform checked">
        <ListHead>What the platform checked</ListHead>
        {fix.checks.length > 0 ? (
          <ul className={styles['rows']}>
            {fix.checks.map((check) => (
              <li key={check.check}>
                <b>{check.passed ? 'Passed' : 'Did not pass'}</b> <span>{check.words}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p>{NO_CHECKS}</p>
        )}
        <p className="muted">{CHECKS_ARE_CODES}</p>
      </section>
    </>
  )
}
