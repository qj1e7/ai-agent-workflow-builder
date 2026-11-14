import { useContext, useEffect, useState } from 'react'
import { useApproval, useRun } from '../../api/queries'
import type { ApprovalItem, RunView } from '../../api/types'
import { Card } from '../../ui/Card'
import { cx } from '../../ui/cx'
import { IconCheck } from '../../ui/icons'
import { OpenButton } from '../../ui/OpenItem'
import { approvalPill, approvalTitle, cardStatusWords, turnWords } from '../run/approvalWords'
import { standingOf } from '../run/decision'
import { count, titleOf, type NameOf, type StageFacts } from '../run/words'
import { stageOfRun } from '../workflows/workflow'
import { useShowBesideOnWide } from './autoOpen'
import { CardMemoryContext, type RequestRef } from './cardMemory'
import { approvalItem } from './home'
import { useMainButton } from './primary'
import pills from '../run/RunPage.module.css'
import styles from './Planner.module.css'

/** The chat shows this many requests, newest first, then how many more. */
export const REQUESTS_SHOWN = 3

/** How often a card reads its run while the approved write is being made, so "Approved." becomes "Approved. MOCK-22 created.". */
const WRITING_POLL_MS = 2_000

/** The run's facts, with the keys of what it wrote, so the card names the ticket it made. */
function factsOfRun(run: RunView): StageFacts {
  const facts = stageOfRun(run)
  return run.state === 'succeeded' ? { ...facts, refs: run.written.map((write) => write.external_reference).filter((ref) => ref !== '') } : facts
}

/**
 * One request as the sketch's approval card: what it writes, its pill, the first change, and Review and decide or Open. It follows
 * the request, so after a decision it keeps its place and says what happened at the left of its foot.
 */
function ApprovalCard({ request, main, nameOf }: { request: RequestRef; main: boolean; nameOf: NameOf }) {
  const approval = useApproval(request.approvalId)
  const shown = approval.data
  const standing = shown ? standingOf(shown.steps) : null
  const run = useRun(request.runId, { poll: standing?.is === 'approved' ? WRITING_POLL_MS : false })
  if (!shown || !standing) {
    return (
      <p className="muted" role="status">
        {approval.isError ? 'I couldn’t read that request just now.' : 'Reading the request'}
      </p>
    )
  }
  const canDecide = shown.you_can_decide && standing.is === 'open'
  const pill = approvalPill(standing, canDecide)
  const done = cardStatusWords(standing, run.data ? factsOfRun(run.data) : null)
  const [first] = shown.actions
  const summary = first ? titleOf(first) : null
  const others = shown.actions.length - 1
  const turn = turnWords(standing, nameOf)
  return (
    <Card
      title={approvalTitle(shown.actions)}
      pill={
        <span className={cx(pills['pill'], pills[pill.tone])} data-approval-pill>
          {pill.label}
        </span>
      }
      status={
        done === null ? undefined : (
          <span className={cx(styles['cardDone'], standing.is === 'approved' && styles['cardOk'])}>
            {standing.is === 'approved' ? <IconCheck size={15} /> : null}
            {done}
          </span>
        )
      }
      actions={
        <OpenButton variant={canDecide && main ? 'primary' : 'secondary'} item={approvalItem(request.runId)} to={`/runs/${request.runId}`}>
          {canDecide ? 'Review and decide' : 'Open'}
        </OpenButton>
      }
    >
      {summary ? <p>{others > 0 ? `${summary}, and ${count(others, 'more change')}` : summary}</p> : null}
      {turn ? <p className="muted">{turn}</p> : null}
    </Card>
  )
}

interface ApprovalCardsProps {
  /** The requests waiting for this person's yes, newest first, from the same list as Needs you. */
  readonly items: readonly ApprovalItem[]
  readonly total: number
  readonly nameOf: NameOf
}

/**
 * The requests waiting for this person's yes as cards, three at most, then how many more, which opens Needs you. The answer keeps
 * the requests it first showed, so a card stays after its decision. With one, it opens beside the chat on a wide screen.
 */
export function ApprovalCards({ items, total, nameOf }: ApprovalCardsProps) {
  const memory = useContext(CardMemoryContext).approvals
  const [pinned] = useState<readonly RequestRef[]>(() => memory.kept() ?? items.slice(0, REQUESTS_SHOWN).map((item) => ({ approvalId: item.approval_id, runId: item.run_id })))
  useEffect(() => memory.keep(pinned), [memory, pinned])
  const [only] = pinned
  useShowBesideOnWide(pinned.length === 1 && only ? approvalItem(only.runId) : null)
  const main = useMainButton() === 'primary'
  const left = total - pinned.length
  return (
    <>
      {pinned.map((request, index) => (
        <ApprovalCard key={request.approvalId} request={request} main={main && index === 0} nameOf={nameOf} />
      ))}
      {left > 0 ? (
        <p className={styles['more']}>
          <OpenButton item={{ kind: 'needs' }} to="/workflows">
            {`${String(left)} more`}
          </OpenButton>
        </p>
      ) : null}
    </>
  )
}
