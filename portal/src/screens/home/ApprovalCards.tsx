import { useContext, useEffect, useMemo, useState } from 'react'
import type { Pager } from '../../api/homeQueries'
import { useApproval, useRun } from '../../api/queries'
import type { RunView } from '../../api/types'
import { Card } from '../../ui/Card'
import { cx } from '../../ui/cx'
import { IconCheck } from '../../ui/icons'
import { OpenButton } from '../../ui/OpenItem'
import { ShowMore } from '../../ui/ShowMore'
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

/** The chat shows this many requests at a time, newest first. */
export const REQUESTS_SHOWN = 3

/** How often a card reads its run while the approved write is being made, so "Approved." becomes "Approved. MOCK-22 created.". */
const WRITING_POLL_MS = 2_000

/** The run's facts, with the keys of what it wrote, so the card names the ticket it made. */
function factsOfRun(run: RunView): StageFacts {
  const facts = stageOfRun(run)
  return run.state === 'succeeded' ? { ...facts, refs: run.written.map((write) => write.external_reference).filter((ref) => ref !== '') } : facts
}

const READING = (failed: boolean) => (
  <p className="muted" role="status">
    {failed ? 'I couldn’t read that request just now.' : 'Reading the request'}
  </p>
)

interface CardProps {
  readonly request: RequestRef
  readonly main: boolean
  readonly nameOf: NameOf
}

/** A request waiting for someone else's yes is known by its run, which names its approval. */
function ApprovalCard({ request, main, nameOf }: CardProps) {
  const run = useRun(request.approvalId === null ? request.runId : '')
  if (request.approvalId !== null) return <RequestCard request={{ ...request, approvalId: request.approvalId }} main={main} nameOf={nameOf} />
  const approvalId = run.data && 'approval' in run.data ? run.data.approval.approval_id : null
  return approvalId === null ? READING(run.isError) : <RequestCard request={{ ...request, approvalId }} main={main} nameOf={nameOf} />
}

/**
 * One request as the sketch's approval card: what it writes, its pill, the first change, and Review and decide or Open. It follows
 * the request, so after a decision it keeps its place and says what happened at the left of its foot.
 */
function RequestCard({ request, main, nameOf }: { request: RequestRef & { readonly approvalId: string }; main: boolean; nameOf: NameOf }) {
  const approval = useApproval(request.approvalId)
  const shown = approval.data
  const standing = shown ? standingOf(shown.steps) : null
  const run = useRun(request.runId, { poll: standing?.is === 'approved' ? WRITING_POLL_MS : false })
  if (!shown || !standing) return READING(approval.isError)
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
  /** The requests, newest first: those waiting for this person's yes from the same list as Needs you, or their own that wait for another's. */
  readonly items: readonly RequestRef[]
  readonly total: number
  readonly nameOf: NameOf
  /**
   * For their own requests, which Needs you doesn't list: the rest come here, three at a time, with Show more, reading the next page
   * when the cards run past what is read. Without it, “N more” opens Needs you, which lists every request waiting for their yes.
   */
  readonly more?: Pager
}

/**
 * The requests as cards, three at first, then the rest in Needs you or with Show more. The answer keeps the requests it showed,
 * so a card stays after its decision. With one, it opens beside the chat on a wide screen.
 */
export function ApprovalCards({ items, total, nameOf, more }: ApprovalCardsProps) {
  const memory = useContext(CardMemoryContext).approvals
  const [followed, setFollowed] = useState<readonly RequestRef[]>(() => memory.kept() ?? items.slice(0, REQUESTS_SHOWN))
  const [wanted, setWanted] = useState(followed.length)
  const shown = useMemo(() => {
    const fresh = items.filter((item) => !followed.some((request) => request.runId === item.runId))
    return [...followed, ...fresh.slice(0, Math.max(0, wanted - followed.length))]
  }, [followed, items, wanted])
  useEffect(() => memory.keep(shown), [memory, shown])
  const [only] = shown
  useShowBesideOnWide(shown.length === 1 && only ? approvalItem(only.runId) : null)
  const main = useMainButton() === 'primary'
  const left = Math.max(0, total - shown.length)
  // A card stays after its request is decided, while the platform's total counts only what still waits, so the count adds the
  // decided cards to it, and the line agrees with the cards drawn.
  const stillWaiting = shown.filter((request) => items.some((item) => item.runId === request.runId)).length
  const decided = shown.length - stillWaiting
  const pager: Pager | null = more
    ? {
        busy: more.busy,
        failed: more.failed,
        showMore: () => {
          setFollowed(shown)
          setWanted(shown.length + REQUESTS_SHOWN)
          if (items.length - stillWaiting < REQUESTS_SHOWN && items.length < total) more.showMore()
        },
      }
    : null
  return (
    <>
      {shown.map((request, index) => (
        <div key={request.runId} data-run-card={request.runId} className={styles['cardSlot']}>
          <ApprovalCard request={request} main={main && index === 0} nameOf={nameOf} />
        </div>
      ))}
      {pager ? (
        <ShowMore shown={shown.length} total={total + decided} pager={pager} keys={shown.map((request) => request.runId)} rowAttr="data-run-card" />
      ) : left > 0 ? (
        <p className={styles['more']}>
          <OpenButton item={{ kind: 'needs' }} to="/workflows">
            {`${String(left)} more`}
          </OpenButton>
        </p>
      ) : null}
    </>
  )
}
