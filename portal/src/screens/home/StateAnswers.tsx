import { useEffect, useMemo } from 'react'
import { useDecisions, useHome } from '../../api/homeQueries'
import { useDisplayName } from '../../api/people'
import { useMe, useUseCases, useWatchlist } from '../../api/queries'
import { usePeopleList } from '../../api/settingsQueries'
import type { DecidedReply, HomeOut } from '../../api/types'
import { operatorsSay } from '../../shell/OperatorsNote'
import { ButtonLink } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { OpenButton, OpenLink } from '../../ui/OpenItem'
import { REFRESH_MS, rowsOf, viewerOf } from '../workflows/workflow'
import { behindWords, hasNewer, REFRESH_MS as WATCH_REFRESH } from '../software/software'
import { useCapabilities } from '../../api/plannerQueries'
import { ideasSay, needsSay, startingPoints, workflowsSay } from './answers'
import { useAsker } from './asker'
import { decidedSay, decisionLine } from './decided'
import { approvalItem, approvalsOf, approverLine, moreWords, needsOf, needsTotal, wordsOf } from './home'
import { useShowBesideOnWide } from './autoOpen'
import { NeedRows } from './NeedsSection'
import { SoftwareRows, WorkflowRows } from './panels/ListRows'
import { NeedsMore } from './panels/NeedsMore'
import lists from './panels/Lists.module.css'
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

/** The Workflows card shows this many rows, then a way to the whole list. */
export const WORKFLOWS_SHOWN = 5

/** Check my workflows: the sketch's Workflows card, a few rows from the same list as the Workflows page, for one workflow or all of them. */
export function CheckWorkflowsAnswer({ useCaseId, now, say }: { useCaseId: string | null; now: Date; say: Say }) {
  const me = useMe()
  const useCases = useUseCases({ poll: REFRESH_MS })
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
  if (rows.length === 0) {
    return (
      <>
        <p>{sentence}</p>
        <ButtonLink to="/workflows">Open Workflows</ButtonLink>
      </>
    )
  }
  return (
    <>
      <p>{sentence}</p>
      <Card
        title="Workflows"
        pill={<span className={lists['count']}>{rows.length}</span>}
        {...(rows.length > WORKFLOWS_SHOWN
          ? {
              actions: (
                <OpenButton item={{ kind: 'workflows' }} to="/workflows">
                  See all workflows
                </OpenButton>
              ),
            }
          : {})}
      >
        <WorkflowRows useCases={rows.slice(0, WORKFLOWS_SHOWN).map((row) => row.useCase)} label="Your workflows" now={now} />
      </Card>
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

/** What needs me: the sketch's Needs card. Its head is the sentence, and its body the same Do now and Set up rows as on Home, from the same list as the strip, the panel and the rail. */
export function NeedsMeAnswer({ now, say }: { now: Date; say: Say }) {
  const home = useHome()
  const operator = useAsker() === 'operator'
  const needs = useMemo(() => (home.data ? needsOf(home.data) : null), [home.data])
  const sentence = home.data ? needsSentence(home.data, operator) : null
  useSaidOnce(sentence, say)
  const only = needs?.total === 1 ? needs.shown[0] : undefined
  useShowBesideOnWide(!operator && only?.kind === 'approval' ? { kind: 'approval', id: only.item.run_id } : null)
  if (!needs || sentence === null) {
    return (
      <p className="muted" role="status">
        {home.isError ? 'I couldn’t read what needs you just now.' : 'Checking what needs you'}
      </p>
    )
  }
  if (needs.shown.length === 0) return <p>{sentence}</p>
  return (
    <Card title={sentence.replace(/\.$/, '')}>
      <NeedRows needs={needs.shown} now={now} more={<NeedsMore needs={needs} />} />
    </Card>
  )
}

/** Which software is behind: the sketch's behind card, read from the watchlist with no model. Each row opens the software beside the chat. */
export function BehindAnswer({ now, say }: { now: Date; say: Say }) {
  const watchlist = useWatchlist({ poll: WATCH_REFRESH })
  const view = watchlist.data
  const rows = view?.software
  const behind = useMemo(() => rows?.filter(hasNewer) ?? [], [rows])
  const sentence = rows ? behindWords(rows) : null
  useSaidOnce(sentence, say)
  if (!view || sentence === null) {
    return (
      <p className="muted" role="status">
        {watchlist.isError ? 'I couldn’t read the watchlist just now.' : 'Checking the watchlist'}
      </p>
    )
  }
  if (behind.length === 0) return <p>{sentence}</p>
  return (
    <Card
      title={sentence.replace(/\.$/, '')}
      actions={
        <OpenButton item={{ kind: 'watchlist' }} to="/software">
          See the watchlist
        </OpenButton>
      }
    >
      <SoftwareRows rows={behind} view={view} label="Software with a newer version" now={now} />
    </Card>
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
                <OpenButton variant={index === 0 ? main : 'secondary'} item={approvalItem(need.item.run_id)} to={`/runs/${need.item.run_id}`}>
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
