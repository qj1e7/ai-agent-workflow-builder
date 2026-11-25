import { useState } from 'react'
import { useRefine } from '../../api/draftedQueries'
import { useErrorWords } from '../../api/context'
import { pressOnce, useLatch } from '../../api/latch'
import type { DraftedWorkflowView, RefinementView } from '../../api/types'
import { Button } from '../../ui/Button'
import styles from './Drafted.module.css'

export const REFINE_IT = 'Refine it'
/** What refining does and never does, beside the button, so nobody reads it as turning anything on (principle 6). */
export const REFINE_NEVER = 'Nothing turns on and nothing is written. A refined draft is checked again.'

/** One round as code counted it: the cases that apply, and how many passed. */
export function roundWords(round: RefinementView['rounds'][number]): string {
  return `Round ${round.round}: ${round.passed} of ${round.scenarios} ${round.scenarios === 1 ? 'case' : 'cases'} passed.`
}

/**
 * Refining the newest revision's Check on practice systems (ADR 0054, section 7). The platform's own words lead: offered,
 * refining, refined, unchanged, or given up with why. Each round shows as code counted it. Only an Operator who can start it
 * sees the button, and it never stands in for the Check, the set-up approval or the real test run.
 */
export function Refinement({ view, refinement }: { view: DraftedWorkflowView; refinement: RefinementView }) {
  const refine = useRefine(view.drafted_id)
  const words = useErrorWords()
  const latch = useLatch()
  const [problem, setProblem] = useState<string | null>(null)
  const refining = refinement.state === 'refining'
  return (
    <section className={styles['simulation']} aria-label="Refining on practice systems" data-refinement={refinement.state}>
      <p className={styles['said']} role={refining ? 'status' : undefined}>
        {refinement.said}
      </p>
      {refinement.rounds.length > 0 ? (
        <ul className={styles['cases']}>
          {refinement.rounds.map((round) => (
            <li key={round.round} className={styles['case']}>
              {roundWords(round)}
            </li>
          ))}
        </ul>
      ) : null}
      {refinement.state === 'offered' && refinement.can_start ? (
        <>
          <p className={styles['note']}>{REFINE_NEVER}</p>
          <p>
            <Button
              loading={refine.isPending}
              onClick={() =>
                pressOnce(latch, (outcome) => refine.mutate(view.revision, outcome), {
                  onSuccess: () => setProblem(null),
                  onError: (error) => setProblem(words(error)),
                })
              }
            >
              {REFINE_IT}
            </Button>
          </p>
        </>
      ) : null}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </section>
  )
}
