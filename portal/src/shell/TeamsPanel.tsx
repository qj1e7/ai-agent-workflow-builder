import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { useApprovals, useRuns, useTeamsMessages } from '../api/queries'
import type { Me, RunView, TeamsStubMessage } from '../api/types'
import { shortTime } from '../screens/run/words'
import { ButtonLink } from '../ui/Button'
import { IconX } from '../ui/icons'
import { motionAllowed } from '../ui/motion'
import { ChatIcon, Mark } from './icons'
import { PRODUCT } from './product'
import { AdaptiveCardView } from './TeamsCard'
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

/** The platform says whether this person can decide each waiting run. Only it knows who owns or retried a run. */
export function badgeAsks(runs: readonly RunView[], messages: readonly TeamsStubMessage[]): BadgeAsks {
  const posted = new Set(messages.map((message) => message.approval_id))
  const ids = runs
    .filter((run) => run.state === 'awaiting_approval')
    .filter((run) => run.you_can_decide)
    .filter((run) => posted.has(run.approval.approval_id))
    .sort((a, b) => b.started_at.localeCompare(a.started_at))
    .map((run) => run.approval.approval_id)
  return { ids: ids.slice(0, BADGE_MAX_ASKS), more: ids.length > BADGE_MAX_ASKS }
}

function linkOf(message: TeamsStubMessage): string {
  return message.link.startsWith('/') ? message.link : `/approvals/${message.approval_id}`
}

/**
 * The message as a real Teams channel shows it: the platform's Adaptive Card, with one link to the
 * approval page and no Approve or Decline button (ADR 0036). The Approver decides on that page.
 */
export function MessageBody({ message, onOpen }: { message: TeamsStubMessage; onOpen: () => void }) {
  return (
    <div className={styles['card']}>
      {message.card ? (
        <AdaptiveCardView card={message.card} onOpen={onOpen} />
      ) : (
        <>
          <p>{message.text}</p>
          <div className={styles['buttons']}>
            <ButtonLink to={linkOf(message)} onClick={onOpen}>
              Open in {PRODUCT}
            </ButtonLink>
          </div>
        </>
      )}
    </div>
  )
}

function Message({ message, onOpen }: { message: TeamsStubMessage; onOpen: () => void }) {
  return (
    <li className={styles['message']} data-approval-id={message.approval_id}>
      <span className={styles['app']}>
        <Mark height={14} />
      </span>
      <div>
        <p className={styles['meta']}>
          <b>{PRODUCT}</b> · {shortTime(message.ts)}
        </p>
        <MessageBody message={message} onOpen={onOpen} />
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
              <Message key={message.id} message={message} onOpen={onOpen} />
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
  const asks = badgeAsks(runs.data ?? [], messages.data ?? [])
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
