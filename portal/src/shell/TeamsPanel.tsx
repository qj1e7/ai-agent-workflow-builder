import { useCallback, useEffect, useRef, useState, type RefObject, type SyntheticEvent } from 'react'
import { displayName, usePeople } from '../api/people'
import { POLL_MS, useApproval, useApprovals, useRuns, useTeamsMessages } from '../api/queries'
import type { ApprovalView, Me, RunView, TeamsStubMessage } from '../api/types'
import { useDecision, type Decision } from '../screens/run/decision'
import { andList, shortTime, teamsLockWords, type NameOf } from '../screens/run/words'
import { Button, ButtonLink } from '../ui/Button'
import { cx } from '../ui/cx'
import { useFocusWhenReady } from '../ui/focus'
import { IconCheck, IconLock, IconX } from '../ui/icons'
import { motionAllowed } from '../ui/motion'
import { ChatIcon, Mark } from './icons'
import { PRODUCT } from './product'
import iconButton from './IconButton.module.css'
import styles from './TeamsPanel.module.css'

export const TEAMS_TITLE = 'Teams, practice copy'
export const TEAMS_EMPTY_WORDS = 'No messages yet. When a run needs a yes, its message shows here.'
const TEAMS_NOTE = 'Practice copy. Nothing reaches the real Teams.'

export const BADGE_POLL_MS = 30_000
export const BADGE_MAX_ASKS = 9
const SHOWN_MESSAGES = 20
const CLOSE_MS = 220

export interface WaitingCount {
  readonly count: number
  readonly atLeast: boolean
}

export function teamsLabel({ count, atLeast }: WaitingCount): string {
  if (count === 0) return TEAMS_TITLE
  if (atLeast) return `${TEAMS_TITLE}, ${count} or more approvals waiting for you`
  return `${TEAMS_TITLE}, ${count === 1 ? '1 approval' : `${count} approvals`} waiting for you`
}

export function badgeText({ count, atLeast }: WaitingCount): string | null {
  if (count === 0) return null
  return atLeast ? `${count}+` : String(count)
}

export interface BadgeAsks {
  readonly ids: readonly string[]
  readonly more: boolean
}

const notStartedBy = (me: string) => (run: RunView) => run.started_by !== me

export function badgeAsks(runs: readonly RunView[], messages: readonly TeamsStubMessage[], me: string): BadgeAsks {
  const posted = new Set(messages.map((message) => message.approval_id))
  const ids = runs
    .filter(notStartedBy(me))
    .filter((run) => run.state === 'awaiting_approval')
    .filter((run) => posted.has(run.approval.approval_id))
    .sort((a, b) => b.started_at.localeCompare(a.started_at))
    .map((run) => run.approval.approval_id)
  return { ids: ids.slice(0, BADGE_MAX_ASKS), more: ids.length > BADGE_MAX_ASKS }
}

export type TeamsAction =
  | { readonly kind: 'loading' }
  | { readonly kind: 'decide' }
  | { readonly kind: 'locked'; readonly words: string }
  | { readonly kind: 'decided'; readonly verdict: 'approve' | 'decline'; readonly by: string }

export function teamsActionOf(approval: ApprovalView | undefined, nameOf: NameOf): TeamsAction {
  if (!approval) return { kind: 'loading' }
  const declined = approval.steps.find((step) => step.status === 'declined')
  if (declined) return { kind: 'decided', verdict: 'decline', by: nameOf(declined.decided_by ?? '') }
  if (approval.steps.length > 0 && approval.steps.every((step) => step.status === 'approved')) {
    return { kind: 'decided', verdict: 'approve', by: andList(approval.steps.map((step) => nameOf(step.decided_by ?? ''))) }
  }
  if (approval.you_can_decide) return { kind: 'decide' }
  return { kind: 'locked', words: teamsLockWords(approval.why_not) }
}

interface ActionsProps {
  readonly action: TeamsAction
  readonly link: string
  readonly decision: Pick<Decision, 'pending' | 'error' | 'decide'>
  readonly onOpen: () => void
}

export function TeamsActions({ action, link, decision, onOpen }: ActionsProps) {
  const open = (
    <ButtonLink to={link} onClick={onOpen}>
      Open in {PRODUCT}
    </ButtonLink>
  )
  switch (action.kind) {
    case 'loading':
      return <div className={styles['buttons']}>{open}</div>
    case 'decide': {
      const busy = decision.pending !== null
      return (
        <>
          <div className={styles['buttons']}>
            <Button variant="approve" loading={decision.pending === 'approve'} disabled={busy && decision.pending !== 'approve'} onClick={() => decision.decide('approve')}>
              Approve
            </Button>
            <Button loading={decision.pending === 'decline'} disabled={busy && decision.pending !== 'decline'} onClick={() => decision.decide('decline')}>
              Decline
            </Button>
            {open}
          </div>
          {decision.error ? (
            <p className={styles['error']} role="alert">
              {decision.error}
            </p>
          ) : null}
        </>
      )
    }
    case 'locked':
      return (
        <>
          <div className={styles['lock']}>
            <IconLock size={18} />
            <span>{action.words}</span>
          </div>
          <div className={styles['buttons']}>{open}</div>
        </>
      )
    case 'decided':
      return (
        <>
          <span className={cx(styles['pill'], action.verdict === 'approve' ? styles['ok'] : styles['bad'])} tabIndex={-1} data-decided="">
            {action.verdict === 'approve' ? <IconCheck size={12} /> : <IconX size={12} />}
            {action.verdict === 'approve' ? `Approved by ${action.by}` : `Declined by ${action.by}`}
          </span>
          <div className={styles['buttons']}>{open}</div>
        </>
      )
  }
}

function linkOf(message: TeamsStubMessage): string {
  return message.link.startsWith('/') ? message.link : `/approvals/${message.approval_id}`
}

interface OnScreen {
  readonly now: boolean
  readonly ever: boolean
}

const ALWAYS_ON_SCREEN: OnScreen = { now: true, ever: true }

function useOnScreen(ref: RefObject<Element | null>): OnScreen {
  const [seen, setSeen] = useState<OnScreen>(() => (typeof IntersectionObserver === 'function' ? { now: false, ever: false } : ALWAYS_ON_SCREEN))
  useEffect(() => {
    const node = ref.current
    if (!node || typeof IntersectionObserver !== 'function') return
    const watch = new IntersectionObserver((entries) => {
      const now = entries.at(-1)?.isIntersecting ?? false
      setSeen((was) => (was.now === now ? was : { now, ever: was.ever || now }))
    })
    watch.observe(node)
    return () => watch.disconnect()
  }, [ref])
  return seen
}

function Message({ message, nameOf, onOpen }: { message: TeamsStubMessage; nameOf: NameOf; onOpen: () => void }) {
  const item = useRef<HTMLLIElement>(null)
  const onScreen = useOnScreen(item)
  const approval = useApproval(message.approval_id, { poll: onScreen.now ? POLL_MS : false, enabled: onScreen.ever })
  const action = teamsActionOf(approval.data, nameOf)
  const focusPill = useFocusWhenReady(action.kind === 'decided', () => item.current?.querySelector<HTMLElement>('[data-decided]'))
  const decision = useDecision(approval.data, null, focusPill)

  return (
    <li className={styles['message']} ref={item} data-approval-id={message.approval_id}>
      <span className={styles['app']}>
        <Mark height={14} />
      </span>
      <div>
        <p className={styles['meta']}>
          <b>{PRODUCT}</b> · {shortTime(message.ts)}
        </p>
        <div className={styles['card']}>
          <p>{message.text}</p>
          <TeamsActions action={action} link={linkOf(message)} decision={decision} onOpen={onOpen} />
        </div>
      </div>
    </li>
  )
}

/** Like a Teams channel, the panel shows its newest message at the bottom, and stays there as messages load, until the person scrolls. */
function useStuckToBottom(): (node: HTMLDivElement | null) => (() => void) | undefined {
  return useCallback((node: HTMLDivElement | null) => {
    const grows = node?.querySelector('[data-grows]')
    if (!node || !grows || typeof ResizeObserver !== 'function') return undefined
    let stuck = true
    const release = () => {
      stuck = false
    }
    const watch = new ResizeObserver(() => {
      if (stuck) node.scrollTop = node.scrollHeight
    })
    watch.observe(grows)
    node.addEventListener('wheel', release, { passive: true })
    node.addEventListener('touchmove', release, { passive: true })
    node.addEventListener('keydown', release)
    return () => {
      watch.disconnect()
      node.removeEventListener('wheel', release)
      node.removeEventListener('touchmove', release)
      node.removeEventListener('keydown', release)
    }
  }, [])
}

function Drawer({ me, onClose, onOpen }: { me: Me; onClose: () => void; onOpen: () => void }) {
  const messages = useTeamsMessages({ poll: true })
  const people = usePeople()
  const nameOf: NameOf = (id) => displayName(people, id)
  const shown = (messages.data ?? []).slice(-SHOWN_MESSAGES)
  const channel = shown.at(-1)?.channel
  const inner = useStuckToBottom()

  return (
    <div className={styles['inner']} ref={inner}>
      <div className={styles['head']}>
        <div>
          <h2>Microsoft Teams</h2>
          <small>{TEAMS_NOTE}</small>
        </div>
        <button type="button" className={styles['close']} aria-label="Close Teams" onClick={onClose} data-close="">
          <IconX size={18} />
        </button>
      </div>
      <p className={styles['channel']}>
        {channel ? <b># {channel}</b> : null}
        <span className={styles['signedIn']}>
          {channel ? ' · ' : ''}signed in as {me.display}
        </span>
      </p>
      <div data-grows="">
        {shown.length > 0 ? (
          <ol className={styles['messages']} aria-label="Messages">
            {shown.map((message) => (
              <Message key={message.id} message={message} nameOf={nameOf} onOpen={onOpen} />
            ))}
          </ol>
        ) : (
          <p className={styles['empty']}>{messages.isPending ? 'Loading messages' : TEAMS_EMPTY_WORDS}</p>
        )}
      </div>
    </div>
  )
}

function useWaitingForYou(person: Me | null): WaitingCount {
  const enabled = person !== null
  const messages = useTeamsMessages({ poll: BADGE_POLL_MS, enabled })
  const runs = useRuns({ poll: BADGE_POLL_MS, enabled })
  const asks = badgeAsks(runs.data ?? [], messages.data ?? [], person?.id ?? '')
  const approvals = useApprovals(asks.ids, { poll: BADGE_POLL_MS })
  const count = approvals.filter((query) => query.data?.you_can_decide === true).length
  return { count, atLeast: asks.more && count === asks.ids.length }
}

export function TeamsButton({ person }: { person: Me | null }) {
  const [open, setOpen] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(true)
  const waiting = useWaitingForYou(person)
  const label = teamsLabel(waiting)
  const badge = badgeText(waiting)
  const drawn = open && person !== null

  // Chrome may put first focus on the panel's scrolling area, so focus goes to Close itself.
  // A press before the person is known opens an empty dialog, and Close gets focus once the drawer is drawn.
  useEffect(() => {
    const node = dialog.current
    if (!open || !node) return
    if (!node.open) node.showModal()
    if (drawn) node.querySelector<HTMLElement>('[data-close]')?.focus()
  }, [open, drawn])

  function close(focusButton = true): void {
    const node = dialog.current
    if (!node?.open) return
    returnFocus.current = focusButton
    if (!motionAllowed()) {
      node.close()
      return
    }
    node.dataset['leaving'] = ''
    window.setTimeout(() => {
      delete node.dataset['leaving']
      node.close()
    }, CLOSE_MS)
  }

  function onCancel(event: SyntheticEvent<HTMLDialogElement>): void {
    event.preventDefault()
    close()
  }

  function onClosed(): void {
    setOpen(false)
    if (returnFocus.current) button.current?.focus()
    returnFocus.current = true
  }

  return (
    <>
      <button ref={button} type="button" className={iconButton['button']} aria-label={label} title={label} onClick={() => setOpen(true)}>
        <ChatIcon />
        <span className={iconButton['label']}>Teams</span>
        {badge ? (
          <span className={styles['badge']} aria-hidden="true">
            {badge}
          </span>
        ) : null}
      </button>
      {/* A press on the dimmed page beside the drawer closes it, as Escape does from the keyboard. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions */}
      <dialog
        ref={dialog}
        className={styles['drawer']}
        aria-label={TEAMS_TITLE}
        onCancel={onCancel}
        onClose={onClosed}
        onClick={(event) => {
          if (event.target === event.currentTarget) close()
        }}
      >
        {drawn ? <Drawer me={person} onClose={() => close()} onOpen={() => close(false)} /> : null}
      </dialog>
    </>
  )
}
