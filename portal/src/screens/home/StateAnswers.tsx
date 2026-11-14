import { useContext, useEffect, useMemo } from 'react'
import { useDecisions, useHome } from '../../api/homeQueries'
import { useDisplayName } from '../../api/people'
import { useMe, useUseCases, useWatchlist } from '../../api/queries'
import { usePeopleList } from '../../api/settingsQueries'
import type { ApprovalItem, DecidedReply, HomeOut } from '../../api/types'
import { operatorsSay } from '../../shell/OperatorsNote'
import { ButtonLink } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { OpenButton } from '../../ui/OpenItem'
import { REFRESH_MS, rowsOf, viewerOf } from '../workflows/workflow'
import { behindWords, hasNewer, REFRESH_MS as WATCH_REFRESH } from '../software/software'
import { useCapabilities } from '../../api/plannerQueries'
import { ideasSay, needsSay, startingPoints, workflowsSay } from './answers'
import { useAsker } from './asker'
import { leadWords } from '../run/approvalWords'
import { ApprovalCards } from './ApprovalCards'
import { CardMemoryContext } from './cardMemory'
import { decidedSay } from './decided'
import { approvalsOf, approverLine, needsOf, needsTotal, type Needs } from './home'
import { NeedRows } from './NeedsSection'
import { DecisionRows, SoftwareRows, WorkflowRows } from './panels/ListRows'
import { NeedsMore } from './panels/NeedsMore'
import lists from './panels/Lists.module.css'

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

/** Only requests wait for this person, so the answer is the requests themselves, as the sketch's approval cards. */
const onlyRequests = (home: HomeOut, operator: boolean): boolean => !operator && home.approvals_total > 0 && needsTotal(home) === home.approvals_total

/** The requests this answer's cards follow, once it has shown them. A decision takes a request off Home's list, never off the answer. */
const useShownRequests = () => useContext(CardMemoryContext).approvals.kept()

/**
 * What needs me: the sketch's Needs card. Its head is the sentence, and its body the same Do now and Set up rows as on Home, from
 * the same list as the strip, the panel and the rail. For an Approver whom only requests wait for, it is the approval cards.
 */
export function NeedsMeAnswer({ now, say }: { now: Date; say: Say }) {
  const home = useHome()
  const operator = useAsker() === 'operator'
  const nameOf = useDisplayName()
  const needs = useMemo(() => (home.data ? needsOf(home.data) : null), [home.data])
  const shown = useShownRequests()
  const requests = home.data && (shown !== undefined || onlyRequests(home.data, operator)) ? approvalsOf(home.data) : null
  const sentence = home.data ? (requests ? leadWords(shown?.length ?? requests.shown.length) : needsSentence(home.data, operator)) : null
  useSaidOnce(sentence, say)
  if (requests && sentence !== null) {
    return (
      <>
        <p>{sentence}</p>
        <ApprovalCards items={requestItems(requests)} total={requests.total} nameOf={nameOf} />
      </>
    )
  }
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

const requestItems = (needs: Needs): ApprovalItem[] => needs.shown.flatMap((need) => (need.kind === 'approval' ? [need.item] : []))

/**
 * The requests waiting for this person’s yes, as the sketch's approval cards, the newest few and how many more. It is what an
 * approve, a decline or a refused way around the gate offers instead: the request, where they decide.
 */
export function RequestsToOpen() {
  const home = useHome()
  const nameOf = useDisplayName()
  const needs = useMemo(() => (home.data ? approvalsOf(home.data) : null), [home.data])
  const shown = useShownRequests()
  if (!needs || (needs.total === 0 && shown === undefined)) return null
  return <ApprovalCards items={requestItems(needs)} total={needs.total} nameOf={nameOf} />
}

/** An approve or decline asked in the chat: nobody decides there, so the answer is the requests waiting for this person’s yes, to open. */
export function DecideAnswer({ say }: { say: Say }) {
  const home = useHome()
  const total = home.data?.approvals_total
  const shown = useShownRequests()
  const sentence = total === undefined ? null : total > 0 || shown !== undefined ? DECIDE_SAY : NOTHING_TO_DECIDE
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
      <RequestsToOpen />
    </>
  )
}

const DECIDED_TITLE = { approve: 'Your recent approvals', decline: 'Your recent declines' } as const

/**
 * This person’s own decisions as the sketch's decisions card: newest first, each row its workflow, the day with a decline's
 * reason or what a yes led to, and Approved or Declined. Each row opens the run. With none, the sentence says so.
 */
export function DecidedAnswer({ only, now, say }: { only: DecidedReply['only']; now: Date; say: Say }) {
  const decisions = useDecisions(only)
  const nameOf = useDisplayName()
  const view = decisions.data
  const sentence = view ? decidedSay(view.total, view.decisions.length, only) : null
  useSaidOnce(sentence, say)
  if (!view) {
    return (
      <p className="muted" role="status">
        {decisions.isError ? 'I couldn’t read your decisions just now.' : 'Checking your decisions'}
      </p>
    )
  }
  if (view.decisions.length === 0) return <p>{sentence}</p>
  return (
    <Card title={only === null ? 'Your recent decisions' : DECIDED_TITLE[only]} status={view.decisions.length < view.total ? sentence : undefined}>
      <DecisionRows decisions={view.decisions} label="Your decisions" now={now} nameOf={nameOf} />
    </Card>
  )
}

/** A change asked by someone who isn’t an Operator: who makes changes, named from the People list, and nothing that changes anything. */
export function OperatorsAnswer({ say }: { say: Say }) {
  const people = usePeopleList()
  const sentence = operatorsSay(people.data)
  useSaidOnce(people.isPending ? null : sentence, say)
  return <p>{sentence}</p>
}
