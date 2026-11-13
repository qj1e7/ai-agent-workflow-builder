import { useEffect, useMemo } from 'react'
import { Link } from '../../ui/Link'
import { useDecisions, useHome } from '../../api/homeQueries'
import { useDisplayName } from '../../api/people'
import { useMe, useUseCases } from '../../api/queries'
import { usePeopleList } from '../../api/settingsQueries'
import type { DecidedReply, HomeOut } from '../../api/types'
import { operatorsSay } from '../../shell/OperatorsNote'
import { ButtonLink } from '../../ui/Button'
import { OpenButton, OpenLink } from '../../ui/OpenItem'
import { listClass, WorkflowRow } from '../workflows/WorkflowsPage'
import { REFRESH_MS, rowsOf, viewerOf } from '../workflows/workflow'
import { useCapabilities } from '../../api/plannerQueries'
import { ideasSay, needsSay, startingPoints, workflowsSay } from './answers'
import { useAsker } from './asker'
import { decidedSay, decisionLine } from './decided'
import { approvalsOf, approverLine, moreWords, needsOf, needsTotal, SEE_ALL_WORDS, wordsOf, type Needs } from './home'
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
  const useCases = useUseCases({ poll: REFRESH_MS })
  const nameOf = useDisplayName()
  const rows = useMemo(() => {
    if (!me.data || !useCases.data) return null
    const all = rowsOf(useCases.data, viewerOf(me.data), 'all', '', NOTHING)
    return useCaseId === null ? all : all.filter((row) => row.useCase.use_case_id === useCaseId)
  }, [me.data, useCases.data, useCaseId])
  const asker = useAsker()
  const sentence = rows ? workflowsSay(rows, asker) : null
  useSaidOnce(sentence, say)
  if (!rows) {
    return (
      <p className="muted" role="status">
        {useCases.isError ? 'I couldn’t read your workflows just now.' : 'Checking your workflows'}
      </p>
    )
  }
  return (
    <>
      <p>{sentence}</p>
      {rows.length > 0 ? (
        <ul className={listClass(rows, styles['wfcheck'])} aria-label="Your workflows">
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

/** The sentence over the starting points, counted from the same list the chips under it are drawn from. */
export function IdeasSentence({ say }: { say: Say }) {
  const capabilities = useCapabilities()
  const sentence = capabilities.data ? ideasSay(startingPoints(capabilities.data).length) : null
  useSaidOnce(sentence, say)
  return sentence === null ? null : <p>{sentence}</p>
}

/** The sentence for what needs me. Someone who isn’t an Operator hears their Home line, so the two never say it differently. */
function needsSentence(home: HomeOut, operator: boolean): string {
  return operator ? needsSay(needsTotal(home)) : approverLine(home)
}

/**
 * Needs you inside an answer, every row it holds. When some aren’t shown, an Operator gets the link to Workflows. Workflows lists no
 * more for someone who isn’t an Operator, so they are told how many are left instead, as their Home does.
 */
function NeedsInAnswer({ needs, now }: { needs: Needs; now: Date }) {
  const main = useMainButton()
  const arrival = useArrival([])
  const asker = useAsker()
  const left = needs.total - needs.shown.length
  const said = asker === 'approver' ? moreWords(needs.more) : null
  if (needs.shown.length === 0) return null
  return (
    <NeedsSection
      needs={needs}
      now={now}
      arrival={{ ...arrival, page: false }}
      quiet={main === 'secondary'}
      more={
        said !== null ? (
          <p className={styles['more']}>{said}</p>
        ) : left > 0 && asker === 'operator' ? (
          <p className={styles['more']}>
            <Link to="/workflows">{SEE_ALL_WORDS}</Link>
          </p>
        ) : null
      }
      whenNone={null}
    />
  )
}

/** What needs me: every row of Needs you the platform returned, grouped, from the same list, so the number here and on the rail are one number. */
export function NeedsMeAnswer({ now, say }: { now: Date; say: Say }) {
  const home = useHome()
  const operator = useAsker() === 'operator'
  const needs = useMemo(() => (home.data ? needsOf(home.data) : null), [home.data])
  const sentence = home.data ? needsSentence(home.data, operator) : null
  useSaidOnce(sentence, say)
  if (!needs || sentence === null) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read what needs you just now.' : 'Checking what needs you'}
      </p>
    )
  }
  return (
    <>
      <p>{sentence}</p>
      <NeedsInAnswer needs={needs} now={now} />
    </>
  )
}

export const DECIDE_SAY = 'I can’t approve or decline for you. Open the request to see exactly what it will write, and decide there.'
export const NOTHING_TO_DECIDE = 'Nothing is waiting for your yes, so there’s nothing to decide.'

/** The newest few requests an answer offers to open. */
const REQUESTS_SHOWN = 3

/**
 * The requests waiting for this person’s yes, each with Review and decide, the newest few and how many more. It is
 * what an approve, a decline or a refused way around the gate offers instead: the request, where they decide.
 */
export function RequestsToOpen({ now }: { now: Date }) {
  const home = useHome()
  const main = useMainButton()
  const needs = useMemo(() => (home.data ? approvalsOf(home.data) : null), [home.data])
  if (!needs) return null
  const shown = needs.shown.slice(0, REQUESTS_SHOWN)
  const left = needs.total - shown.length
  return (
    <>
      {shown.length > 0 ? (
        <ul className={styles['starters']} aria-label="Requests waiting for your yes">
          {shown.map((need, index) =>
            need.kind === 'approval' ? (
              <li key={need.key} className={styles['starter']}>
                <div>
                  <b>{wordsOf(need, now).title}</b>
                  <span className={styles['note']}>{wordsOf(need, now).meta}</span>
                </div>
                <OpenButton variant={index === 0 ? main : 'secondary'} item={{ kind: 'run', id: need.item.run_id }} to={`/runs/${need.item.run_id}`}>
                  Review and decide
                </OpenButton>
              </li>
            ) : null,
          )}
        </ul>
      ) : null}
      {left > 0 ? <p className={styles['more']}>{moreWords({ approvals: left, others: 0 })}</p> : null}
    </>
  )
}

/** An approve or decline asked in the chat: nobody decides there, so the answer is the requests waiting for this person’s yes, to open. */
export function DecideAnswer({ now, say }: { now: Date; say: Say }) {
  const home = useHome()
  const total = home.data?.approvals_total
  const sentence = total === undefined ? null : total > 0 ? DECIDE_SAY : NOTHING_TO_DECIDE
  useSaidOnce(sentence, say)
  if (sentence === null) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read what waits for your yes just now.' : 'Checking what waits for your yes'}
      </p>
    )
  }
  return (
    <>
      <p>{sentence}</p>
      <RequestsToOpen now={now} />
    </>
  )
}

/** This person’s own decisions, newest first, each with its workflow, Approved or Declined, when, and what it led to. */
export function DecidedAnswer({ only, now, say }: { only: DecidedReply['only']; now: Date; say: Say }) {
  const decisions = useDecisions(only)
  const me = useMe().data
  const nameOf = useDisplayName()
  const view = decisions.data
  const sentence = view ? decidedSay(view.total, view.decisions.length, only) : null
  useSaidOnce(sentence, say)
  if (!view || !me) {
    return (
      <p className="muted" role="status">
        {decisions.isError ? 'I couldn’t read your decisions just now.' : 'Checking your decisions'}
      </p>
    )
  }
  return (
    <>
      <p>{sentence}</p>
      {view.decisions.length > 0 ? (
        <ul className={styles['decided']} aria-label="Your decisions">
          {view.decisions.map((decision) => (
            <li key={`${decision.run_id}:${decision.at}`}>
              <div className={styles['decidedHead']}>
                <h3>
                  <OpenLink item={{ kind: 'run', id: decision.run_id }} to={`/runs/${decision.run_id}`} className={styles['decidedLink']}>
                    {decision.use_case_name}
                  </OpenLink>
                </h3>
                <span className={styles['verdict']} data-verdict={decision.verdict}>
                  {decision.verdict === 'approve' ? 'Approved' : 'Declined'}
                </span>
              </div>
              <p>{decisionLine(decision, me.id, now, nameOf)}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  )
}

/** A change asked by someone who isn’t an Operator: who makes changes, named from the People list, and nothing that changes anything. */
export function OperatorsAnswer({ say }: { say: Say }) {
  const people = usePeopleList()
  const sentence = operatorsSay(people.data)
  useSaidOnce(people.isPending ? null : sentence, say)
  return <p>{sentence}</p>
}
