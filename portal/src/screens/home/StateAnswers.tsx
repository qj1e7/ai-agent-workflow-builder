import { useEffect, useMemo } from 'react'
import { Link } from '../../ui/Link'
import { useDecisions, useHome } from '../../api/homeQueries'
import { useDisplayName } from '../../api/people'
import { isOperator } from '../../api/me'
import { useMe, useModelOff, useTroubleshoot, useUseCases } from '../../api/queries'
import { usePeopleList } from '../../api/settingsQueries'
import type { DecidedReply, FailureReason, HomeOut, UseCaseView } from '../../api/types'
import { operatorsSay } from '../../shell/OperatorsNote'
import { ButtonLink } from '../../ui/Button'
import { OpenButton, OpenLink } from '../../ui/OpenItem'
import { listClass, WorkflowRow } from '../workflows/WorkflowsPage'
import { REFRESH_MS, rowsOf, viewerOf } from '../workflows/workflow'
import { useCapabilities } from '../../api/plannerQueries'
import { ideasSay, needsSay, startingPoints, workflowsSay } from './answers'
import { Troubleshooting } from '../run/Outcome'
import { useAsker } from './asker'
import { decidedSay, decisionLine } from './decided'
import { approvalsOf, approverLine, moreWords, needsOf, needsTotal, SEE_ALL_WORDS, type Needs } from './home'
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

/** An approve or decline asked in the chat: nobody decides there, so the answer is the requests waiting for this person’s yes, to open. */
export function DecideAnswer({ now, say }: { now: Date; say: Say }) {
  const home = useHome()
  const needs = useMemo(() => (home.data ? approvalsOf(home.data) : null), [home.data])
  const sentence = needs === null ? null : needs.total > 0 ? DECIDE_SAY : NOTHING_TO_DECIDE
  useSaidOnce(sentence, say)
  if (!needs) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read what waits for your yes just now.' : 'Checking what waits for your yes'}
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

interface Stop {
  readonly run_id: string
  readonly use_case_name: string
  readonly reason: FailureReason
  readonly retryable: boolean
}

/**
 * The stop the answer is about. An Operator’s comes from the stopped list Needs you is made from. Needs you lists no stops for
 * someone who isn’t an Operator, so theirs comes from the workflows’ last runs, which their Workflows page shows as Stopped.
 */
function stopOf(useCaseId: string | null, operator: boolean, home: HomeOut | undefined, list: readonly UseCaseView[] | undefined): Stop | null | undefined {
  const asked = (id: string) => useCaseId === null || id === useCaseId
  if (operator) return home ? (home.stopped.find((item) => asked(item.use_case_id)) ?? null) : undefined
  if (!list) return undefined
  for (const { use_case_id, name, last_run } of list) {
    if (asked(use_case_id) && last_run?.state === 'failed' && last_run.reason !== null) return { run_id: last_run.run_id, use_case_name: name, reason: last_run.reason, retryable: last_run.retryable }
  }
  return null
}

/**
 * Why it stopped: the stopped list Needs you is made from, so the answer and the row can't disagree, then the AI
 * troubleshooter's three answers and the next step under them, Retry or Report to support, from the run page's own pieces.
 * Someone who isn't an Operator gets the same answers, with who can retry in place of Retry.
 */
export function WhyStoppedAnswer({ useCaseId, say }: { useCaseId: string | null; say: Say }) {
  const home = useHome()
  const me = useMe().data
  const operator = isOperator(me)
  const useCases = useUseCases()
  const nameOf = useDisplayName()
  const modelOff = useModelOff()
  const main = useMainButton()
  const stopped = me === undefined ? undefined : stopOf(useCaseId, operator, home.data, useCases.data)
  const troubleshoot = useTroubleshoot(stopped?.run_id ?? '', Boolean(stopped), 0)
  const sentence = stopped === undefined ? null : stopped ? `${stopped.use_case_name} stopped.` : 'Nothing has stopped right now.'
  useSaidOnce(sentence, say)
  if (stopped === undefined) {
    return (
      <p className="muted" role="status">
        {home.isError || useCases.isError ? 'I couldn’t read the stopped workflows just now.' : 'Checking what stopped'}
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
  const titleId = `why-${stopped.run_id}`
  const failure = { state: 'failed', stage: 'working', reason: stopped.reason, retryable: stopped.retryable, message: '' } as const
  return (
    <section className={styles['pcard']} aria-labelledby={titleId}>
      <div className={styles['pcardHead']}>
        <h3 id={titleId}>{stopped.use_case_name} stopped</h3>
      </div>
      <Troubleshooting
        runId={stopped.run_id}
        failure={failure}
        advice={troubleshoot.data}
        loading={troubleshoot.isPending}
        me={me ? { id: me.id, name: me.display, operator: isOperator(me) } : undefined}
        reports={[]}
        nameOf={nameOf}
        modelOff={modelOff}
        quiet={main !== 'primary'}
      />
      <div className={styles['footer']}>
        <OpenButton item={{ kind: 'run', id: stopped.run_id }} to={`/runs/${stopped.run_id}`}>
          See the run
        </OpenButton>
      </div>
    </section>
  )
}
