import { useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { displayName, usePeople } from '../api/people'
import { POLL_MS, useApproval, useApprovals, useRun, useRuns, useTeamsMessages } from '../api/queries'
import type { ApprovalView, Me, TeamsStubMessage } from '../api/types'
import { useDecision, type Decision } from '../screens/run/decision'
import { andList, lockWords, shortTime, type NameOf, type Party } from '../screens/run/words'
import { Button, ButtonLink } from '../ui/Button'
import { cx } from '../ui/cx'
import { IconCheck, IconLock, IconX } from '../ui/icons'
import { motionAllowed } from '../ui/motion'
import { ChatIcon, Mark } from './icons'
import iconButton from './IconButton.module.css'
import styles from './TeamsPanel.module.css'

export const TEAMS_TITLE = 'Teams, practice copy'
export const TEAMS_EMPTY_WORDS = 'No messages yet. When a run needs a yes, its message shows here.'
export const TEAMS_NOTE = 'Practice copy. Nothing reaches the real Teams.'

/** The badge checks this often while the panel is closed. Open, it follows every POLL_MS. */
const BADGE_POLL_MS = 10_000
const SHOWN_MESSAGES = 20
const CLOSE_MS = 220

export function teamsLabel(waiting: number): string {
  if (waiting === 0) return TEAMS_TITLE
  return `${TEAMS_TITLE}, ${waiting === 1 ? '1 approval' : `${waiting} approvals`} waiting for you`
}

export type TeamsAction =
  | { readonly kind: 'loading' }
  | { readonly kind: 'decide' }
  | { readonly kind: 'locked'; readonly words: string }
  | { readonly kind: 'decided'; readonly verdict: 'approve' | 'decline'; readonly by: string }

/** What a Teams message offers the signed-in person, from the approval route's answer for them. */
export function teamsActionOf(approval: ApprovalView | undefined, party: Party | null, nameOf: NameOf): TeamsAction {
  if (!approval) return { kind: 'loading' }
  const declined = approval.steps.find((step) => step.status === 'declined')
  if (declined) return { kind: 'decided', verdict: 'decline', by: nameOf(declined.decided_by ?? '') }
  if (approval.steps.length > 0 && approval.steps.every((step) => step.status === 'approved')) {
    return { kind: 'decided', verdict: 'approve', by: andList(approval.steps.map((step) => nameOf(step.decided_by ?? ''))) }
  }
  if (approval.you_can_decide) return { kind: 'decide' }
  return { kind: 'locked', words: lockWords(approval.why_not, party, true) }
}

interface ActionsProps {
  readonly action: TeamsAction
  readonly link: string
  readonly decision: Pick<Decision, 'pending' | 'error' | 'decide'>
  readonly onOpen: () => void
}

export function TeamsActions({ action, link, decision, onOpen }: ActionsProps) {
  const busy = decision.pending !== null
  switch (action.kind) {
    case 'loading':
      return null
    case 'decide':
      return (
        <>
          <div className={styles['buttons']}>
            <Button variant="approve" loading={decision.pending === 'approve'} disabled={busy && decision.pending !== 'approve'} onClick={() => decision.decide('approve')}>
              Approve
            </Button>
            <Button loading={decision.pending === 'decline'} disabled={busy && decision.pending !== 'decline'} onClick={() => decision.decide('decline')}>
              Decline
            </Button>
            <ButtonLink to={link} onClick={onOpen}>
              Open in Workflow Builder
            </ButtonLink>
          </div>
          {decision.error ? (
            <p className={styles['error']} role="alert">
              {decision.error}
            </p>
          ) : null}
        </>
      )
    case 'locked':
      return (
        <div className={styles['lock']}>
          <IconLock size={18} />
          <span>{action.words}</span>
        </div>
      )
    case 'decided':
      return (
        <span className={cx(styles['pill'], action.verdict === 'approve' ? styles['ok'] : styles['bad'])} tabIndex={-1} data-decided="">
          {action.verdict === 'approve' ? <IconCheck size={12} /> : <IconX size={12} />}
          {action.verdict === 'approve' ? `Approved by ${action.by}` : `Declined by ${action.by}`}
        </span>
      )
  }
}

function linkOf(message: TeamsStubMessage): string {
  return message.link.startsWith('/') ? message.link : `/approvals/${message.approval_id}`
}

function Message({ message, me, nameOf, onOpen }: { message: TeamsStubMessage; me: Me; nameOf: NameOf; onOpen: () => void }) {
  const approval = useApproval(message.approval_id, { poll: POLL_MS })
  const ownWork = approval.data?.why_not === 'own_work'
  const run = useRun(ownWork ? message.run_id : '')
  const party: Party | null = run.data
    ? { startedIt: run.data.started_by === me.id, retriedIt: false, schedule: run.data.trigger === 'schedule' }
    : null
  const item = useRef<HTMLLIElement>(null)
  const focusPill = useRef(false)
  const decision = useDecision(approval.data, party, () => {
    focusPill.current = true
  })
  const action = teamsActionOf(approval.data, party, nameOf)

  // The pressed button goes away once the answer is in, so focus moves to what replaced it.
  useEffect(() => {
    if (!focusPill.current || action.kind !== 'decided') return
    focusPill.current = false
    item.current?.querySelector<HTMLElement>('[data-decided]')?.focus()
  }, [action.kind])

  return (
    <li className={styles['message']} ref={item}>
      <span className={styles['app']}>
        <Mark height={14} />
      </span>
      <div>
        <p className={styles['meta']}>
          <b>Workflow Builder</b> · {shortTime(message.ts)}
        </p>
        <div className={styles['card']}>
          <p>{message.text}</p>
          <TeamsActions action={action} link={linkOf(message)} decision={decision} onOpen={onOpen} />
        </div>
      </div>
    </li>
  )
}

function Drawer({ me, onClose, onOpen }: { me: Me; onClose: () => void; onOpen: () => void }) {
  const messages = useTeamsMessages({ poll: true })
  const people = usePeople()
  const nameOf: NameOf = (id) => displayName(people, id)
  const shown = (messages.data ?? []).slice(-SHOWN_MESSAGES)
  const channel = shown.at(-1)?.channel
  const inner = useRef<HTMLDivElement>(null)
  const loaded = shown.length > 0

  // Like a Teams channel, the newest message is at the bottom, so the panel opens there.
  useEffect(() => {
    if (loaded && inner.current) inner.current.scrollTop = inner.current.scrollHeight
  }, [loaded])

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
      {shown.length > 0 ? (
        <ol className={styles['messages']} aria-label="Messages">
          {shown.map((message) => (
            <Message key={message.id} message={message} me={me} nameOf={nameOf} onOpen={onOpen} />
          ))}
        </ol>
      ) : (
        <p className={styles['empty']}>{messages.isPending ? 'Loading messages' : TEAMS_EMPTY_WORDS}</p>
      )}
    </div>
  )
}

/** How many approvals the signed-in person may decide now: only runs that wait are asked about. */
function useWaitingForYou(enabled: boolean, open: boolean): number {
  const poll = open ? POLL_MS : BADGE_POLL_MS
  const messages = useTeamsMessages({ poll, enabled })
  const runs = useRuns({ poll, enabled })
  const waitingRuns = new Set((runs.data ?? []).filter((run) => run.state === 'awaiting_approval').map((run) => run.run_id))
  const ids = [...new Set((messages.data ?? []).filter((message) => waitingRuns.has(message.run_id)).map((message) => message.approval_id))]
  const approvals = useApprovals(ids, { poll })
  return approvals.filter((query) => query.data?.you_can_decide === true).length
}

/** The header's Teams button and the practice Teams panel it opens, a drawer on the right. */
export function TeamsButton({ person }: { person: Me | null }) {
  const [open, setOpen] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef(true)
  const waiting = useWaitingForYou(person !== null, open)
  const label = teamsLabel(waiting)

  // Chrome may put first focus on the panel's scrolling area, so focus goes to Close itself.
  useEffect(() => {
    const node = dialog.current
    if (!open || !node || node.open) return
    node.showModal()
    node.querySelector<HTMLElement>('[data-close]')?.focus()
  }, [open])

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
        {waiting > 0 ? (
          <span className={styles['badge']} aria-hidden="true">
            {waiting}
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
        {open && person ? <Drawer me={person} onClose={() => close()} onOpen={() => close(false)} /> : null}
      </dialog>
    </>
  )
}
