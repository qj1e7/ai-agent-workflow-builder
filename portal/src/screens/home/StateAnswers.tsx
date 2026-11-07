import { useEffect, useMemo } from 'react'
import { Link } from 'react-router'
import { useHome } from '../../api/homeQueries'
import { useDisplayName } from '../../api/people'
import { useMe, useRuns, useUseCases } from '../../api/queries'
import { ButtonLink } from '../../ui/Button'
import { WorkflowRow } from '../workflows/WorkflowsPage'
import { REFRESH_MS, rowsOf, viewerOf } from '../workflows/workflow'
import wfStyles from '../workflows/Workflows.module.css'
import { needsSay, workflowsSay } from './answers'
import { HOME_NEEDS_SHOWN, needsOf, needsTotal, SEE_ALL_WORDS, stoppedActions, wordsOf } from './home'
import { RetryButton } from './HomeItem'
import { NeedsSection, useArrival } from './NeedsSection'
import { useMainButton } from './primary'
import styles from './Planner.module.css'

const NOTHING: ReadonlySet<string> = new Set()

/** Tells the thread what to read out once the sentence is known. The thread reads each answer once, however often the data refreshes. */
export type Say = (text: string) => void

export function useSaidOnce(text: string | null, say: Say) {
  useEffect(() => {
    if (text !== null) say(text)
  }, [text, say])
}

/** Check my workflows: the rows of the Workflows list, from the same functions, for one workflow or all of them. */
export function CheckWorkflowsAnswer({ useCaseId, now, say }: { useCaseId: string | null; now: Date; say: Say }) {
  const me = useMe()
  const useCases = useUseCases()
  const runs = useRuns({ poll: REFRESH_MS })
  const nameOf = useDisplayName()
  const rows = useMemo(() => {
    if (!me.data || !useCases.data || !runs.data) return null
    const all = rowsOf(useCases.data, runs.data, viewerOf(me.data), 'all', '', NOTHING)
    return useCaseId === null ? all : all.filter((row) => row.useCase.use_case_id === useCaseId)
  }, [me.data, useCases.data, runs.data, useCaseId])
  const sentence = rows ? workflowsSay(rows) : null
  useSaidOnce(sentence, say)
  if (!rows) {
    return (
      <p className="muted" role="status">
        {useCases.isError || runs.isError ? 'I couldn’t read your workflows just now.' : 'Checking your workflows'}
      </p>
    )
  }
  return (
    <>
      <p>{sentence}</p>
      {rows.length > 0 ? (
        <ul className={`${wfStyles['list'] ?? ''} ${styles['wfcheck'] ?? ''}`} aria-label="Your workflows">
          {rows.map((row, index) => (
            <WorkflowRow key={row.useCase.use_case_id} row={row} index={index} primary={false} arrive={false} now={now} nameOf={nameOf} />
          ))}
        </ul>
      ) : (
        <ButtonLink to="/workflows">Open Workflows</ButtonLink>
      )}
    </>
  )
}

/** What needs me: the same rows as Needs you, from the same list, so the number here and on the tab are one number. */
export function NeedsMeAnswer({ now, say }: { now: Date; say: Say }) {
  const home = useHome()
  const main = useMainButton()
  const needs = useMemo(() => (home.data ? needsOf(home.data, HOME_NEEDS_SHOWN) : null), [home.data])
  const arrival = useArrival([])
  const total = home.data ? needsTotal(home.data) : null
  useSaidOnce(total === null ? null : needsSay(total), say)
  if (!needs || total === null) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read what needs you just now.' : 'Checking what needs you'}
      </p>
    )
  }
  const left = total - needs.shown.length
  return (
    <>
      <p>{needsSay(total)}</p>
      {needs.shown.length > 0 ? (
        <NeedsSection
          needs={needs}
          now={now}
          arrival={{ ...arrival, page: false }}
          quiet={main === 'secondary'}
          more={
            left > 0 ? (
              <p className={styles['more']}>
                <Link to="/workflows">{SEE_ALL_WORDS}</Link>
              </p>
            ) : null
          }
          whenNone={null}
        />
      ) : null}
    </>
  )
}

/** Why it stopped: read from the stopped list Needs you is made from, so the answer and the row can't disagree. */
export function WhyStoppedAnswer({ useCaseId, now, say }: { useCaseId: string | null; now: Date; say: Say }) {
  const home = useHome()
  const main = useMainButton()
  const stopped = home.data?.stopped.find((item) => useCaseId === null || item.use_case_id === useCaseId)
  const sentence = !home.data ? null : stopped ? `${stopped.use_case_name} stopped.` : 'Nothing has stopped right now.'
  useSaidOnce(sentence, say)
  if (!home.data) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read the stopped workflows just now.' : 'Checking what stopped'}
      </p>
    )
  }
  if (!stopped) {
    return (
      <>
        <p>{sentence}</p>
        <ButtonLink to="/workflows">Open Workflows</ButtonLink>
      </>
    )
  }
  const need = needsOf(home.data).shown.find((item) => item.kind === 'stopped' && item.item.run_id === stopped.run_id)
  const why = need ? wordsOf(need, now).why : null
  const actions = stoppedActions(stopped.run_id, stopped.retryable)
  const titleId = `why-${stopped.run_id}`
  return (
    <section className={styles['pcard']} aria-labelledby={titleId}>
      <div className={styles['pcardHead']}>
        <h3 id={titleId}>{stopped.use_case_name} stopped</h3>
      </div>
      {why ? (
        <div className={styles['pcardPart']}>
          <p>
            <b>AI troubleshooter</b>
          </p>
          <p>{why}</p>
        </div>
      ) : null}
      <div className={styles['footer']}>
        {actions.map((action, index) =>
          action.kind === 'retry' ? (
            <RetryButton key={action.label} runId={action.runId} label={action.label} primary={index === 0 && main === 'primary'} describedBy={titleId} />
          ) : action.kind === 'open' ? (
            <ButtonLink key={action.label} to={action.to} variant={index === 0 ? main : 'secondary'}>
              {action.label}
            </ButtonLink>
          ) : null,
        )}
      </div>
    </section>
  )
}
