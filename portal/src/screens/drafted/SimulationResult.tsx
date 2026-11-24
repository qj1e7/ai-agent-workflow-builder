import { useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useSimulateAgain } from '../../api/draftedQueries'
import { pressOnce, useLatch } from '../../api/latch'
import type { DraftedSimulationView, SimulatedCaseView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconCheck, IconX } from '../../ui/icons'
import { AI_NOTE, caseLimitWords, casesInOrder, EXPECTED, HAPPENED, KIND_WORDS, NOT_AVAILABLE, NOT_FINISHED, NOT_TRIED_ANYWHERE, SIMULATING, simulationLead, STILL_TESTS, VERDICT_WORDS, YOU_DECIDE } from './simulation'
import styles from './Drafted.module.css'

function Mark({ verdict }: { verdict: SimulatedCaseView['verdict'] }) {
  if (verdict === 'passed') return <IconCheck className={styles['passed']} />
  if (verdict === 'failed') return <IconX className={styles['failed']} />
  return (
    <span className={styles['untried']} aria-hidden="true">
      –
    </span>
  )
}

/** One case: its verdict and kind. A failure adds code's grade, then the AI's note, which only helps. */
function Case({ found }: { found: SimulatedCaseView }) {
  return (
    <li className={styles['case']}>
      <span className={styles['caseHead']}>
        <Mark verdict={found.verdict} />
        <b>{VERDICT_WORDS[found.verdict]}</b> {KIND_WORDS[found.kind]}
      </span>
      {found.verdict === 'failed' ? (
        <>
          <span className={styles['note']}>
            {EXPECTED} {found.expected}
          </span>
          <span className={styles['said']}>
            {HAPPENED} {found.happened}
          </span>
          {found.note ? (
            <span className={styles['note']}>
              {AI_NOTE} {found.note}
            </span>
          ) : null}
        </>
      ) : null}
      {found.verdict === 'not_tried' ? <span className={styles['note']}>{found.happened}</span> : null}
    </li>
  )
}

function TryAgain({ draftedId, revision }: { draftedId: string; revision: number }) {
  const words = useErrorWords()
  const again = useSimulateAgain(draftedId)
  const latch = useLatch()
  const [problem, setProblem] = useState<string | null>(null)
  return (
    <>
      <p>
        <Button loading={again.isPending} onClick={() => pressOnce(latch, (outcome) => again.mutate(revision, outcome), { onSuccess: () => setProblem(null), onError: (error) => setProblem(words(error)) })}>
          Try again
        </Button>
      </p>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </>
  )
}

/**
 * The revision tried on practice systems (ADR 0054, PR 7). The result leads, then what failed and why. A failed case never
 * blocks Turn on, and a pass never stands in for the real test run Turn on starts. It never claims a result it doesn't have.
 */
export function SimulationResult({ simulation, draftedId, revision }: { simulation: DraftedSimulationView; draftedId: string; revision: number }) {
  const again = simulation.can_try_again ? <TryAgain draftedId={draftedId} revision={revision} /> : null
  switch (simulation.state) {
    case 'unavailable':
      return (
        <p className={styles['note']} data-simulation>
          {NOT_AVAILABLE} {STILL_TESTS}
        </p>
      )
    case 'running':
      return (
        <p className={styles['note']} role="status" data-simulation>
          {SIMULATING} {caseLimitWords(simulation.case_seconds)}
        </p>
      )
    case 'not_run':
    case 'not_finished':
      return (
        <div className={styles['simulation']} data-simulation>
          <p className={styles['said']}>{simulation.state === 'not_run' ? simulation.said : NOT_FINISHED}</p>
          {again}
        </div>
      )
    case 'done': {
      const failed = simulation.cases.some((c) => c.verdict === 'failed')
      return (
        <section className={styles['simulation']} aria-label="Practice systems" data-simulation>
          <p className={styles['said']}>
            <b>{simulationLead(simulation)}</b>
          </p>
          {simulation.cases.length > 0 ? (
            <ul className={styles['cases']}>
              {casesInOrder(simulation.cases).map((found) => (
                <Case key={found.kind} found={found} />
              ))}
            </ul>
          ) : null}
          {simulation.not_tried.map((block) => (
            <p key={block.block} className={styles['note']}>
              {`${NOT_TRIED_ANYWHERE} “${block.block}”. ${block.why}`}
            </p>
          ))}
          <p className={styles['note']}>
            {failed ? `${YOU_DECIDE} ` : ''}
            {STILL_TESTS}
          </p>
        </section>
      )
    }
  }
}
