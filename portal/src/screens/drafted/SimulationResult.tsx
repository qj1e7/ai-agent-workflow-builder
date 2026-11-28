import { useState } from 'react'
import { useErrorWords } from '../../api/context'
import { pressOnce, useLatch, type Outcome } from '../../api/latch'
import type { SimulatedCaseView, SimulationView } from '../../api/types'
import { Button } from '../../ui/Button'
import { CardFold } from '../../ui/Card'
import { IconCheck, IconX } from '../../ui/icons'
import { AI_NOTE, caseLimitWords, casesInOrder, EXPECTED, HAPPENED, KIND_WORDS, NOT_AVAILABLE, NOT_FINISHED, NOT_STARTED, NOT_TRIED_ANYWHERE, SIMULATING, simulationLead, STILL_TESTS, VERDICT_WORDS, WAITING, YOU_DECIDE } from './simulation'
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
            <CardFold summary="Details">
              <span className={styles['note']}>
                {AI_NOTE} {found.note}
              </span>
            </CardFold>
          ) : null}
        </>
      ) : null}
      {found.verdict === 'not_tried' ? <span className={styles['note']}>{found.happened}</span> : null}
    </li>
  )
}

/** The cases in order. Folded, the ones that passed open on request and any other stays in view. */
function Cases({ cases, fold }: { cases: readonly SimulatedCaseView[]; fold: boolean }) {
  const list = (items: readonly SimulatedCaseView[]) => (
    <ul className={styles['cases']}>
      {items.map((found) => (
        <Case key={found.kind} found={found} />
      ))}
    </ul>
  )
  const passed = cases.filter((found) => found.verdict === 'passed')
  if (!fold || passed.length === 0) return list(cases)
  const others = cases.filter((found) => found.verdict !== 'passed')
  return (
    <>
      {others.length > 0 ? list(others) : null}
      <details className={styles['foldedCases']}>
        <summary>Show cases</summary>
        {list(passed)}
      </details>
    </>
  )
}

/** Starts the version's try again, wherever its Check is: a drafted revision's, or a workflow's current version. */
export interface TryAgain {
  readonly pending: boolean
  readonly press: (outcome: Outcome<unknown>) => void
}

function TryAgainButton({ tryAgain, label }: { tryAgain: TryAgain; label: string }) {
  const words = useErrorWords()
  const latch = useLatch()
  const [problem, setProblem] = useState<string | null>(null)
  return (
    <>
      <p>
        <Button loading={tryAgain.pending} onClick={() => pressOnce(latch, tryAgain.press, { onSuccess: () => setProblem(null), onError: (error) => setProblem(words(error)) })}>
          {label}
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
 * A version tried on practice systems (ADR 0054): a drafted revision, or a workflow the Planner built from our blocks. The result
 * leads, then what failed and why. A failed case never blocks Turn on, and a pass never stands in for the real test run Turn on
 * starts. It never claims a result it doesn't have. On a workflow's page, and on the draft's card in the chat, the cases that passed fold under the result, a failed one
 * stays in view, and the draft's own line already says a test run still comes first, so this one does not say it again.
 */
export function SimulationResult({ simulation, tryAgain, onWorkflowPage = false, fold = onWorkflowPage, testLineShown = false }: { simulation: SimulationView; tryAgain: TryAgain; onWorkflowPage?: boolean; fold?: boolean; testLineShown?: boolean }) {
  const again = (label: string) => (simulation.can_try_again ? <TryAgainButton tryAgain={tryAgain} label={label} /> : null)
  switch (simulation.state) {
    case 'unavailable':
      return (
        <p className={styles['note']} data-simulation>
          {NOT_AVAILABLE} {STILL_TESTS}
        </p>
      )
    case 'waiting':
      return (
        <p className={styles['note']} data-simulation>
          {WAITING}
        </p>
      )
    case 'not_started':
      return (
        <div className={styles['simulation']} data-simulation>
          <p className={styles['said']}>{NOT_STARTED}</p>
          {again('Try it now')}
        </div>
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
          {again('Try again')}
        </div>
      )
    case 'done': {
      const failed = simulation.cases.some((c) => c.verdict === 'failed')
      return (
        <section className={styles['simulation']} aria-label="Practice systems" data-simulation>
          <p className={styles['said']}>
            <b>{simulationLead(simulation)}</b>
          </p>
          {simulation.cases.length > 0 ? <Cases cases={casesInOrder(simulation.cases)} fold={fold} /> : null}
          {simulation.not_tried.map((block) => (
            <p key={block.block} className={styles['note']}>
              {`${NOT_TRIED_ANYWHERE} “${block.block}”. ${block.why}`}
            </p>
          ))}
          <p className={styles['note']}>
            {failed ? `${YOU_DECIDE} ` : ''}
            {testLineShown ? '' : STILL_TESTS}
          </p>
        </section>
      )
    }
  }
}
