import { useEffect, useId, useRef, useState } from 'react'
import type { ApprovalActionView, ApprovalView } from '../../api/types'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { IconCheck, IconLock } from '../../ui/icons'
import { TicketKeys } from '../jira/TicketKeys'
import { approvalPill, approvalTitle, fieldRows, kindWords, recordWords, sentRowWords, turnWords, waitingWords, whereWords, whyYouWords } from './approvalWords'
import { APPROVE, canDecideNow, standingOf, type Decision, type Standing } from './decision'
import { AskBox, QuestionThread } from './QuestionThread'
import { useFocusAfter, type Questions } from './questions'
import { lockWords, ticketKeysIn, type NameOf, type Party, type StageFacts } from './words'
import styles from './panels.module.css'
import pills from './RunPage.module.css'

type Level = 2 | 3 | 4

const HEADINGS = { 2: 'h2', 3: 'h3', 4: 'h4' } as const

/** What the run didn't check, from notCheckedWords in decision.ts: on the request, waiting or decided, and on the run's record. */
export function NotChecked({ lines, level }: { lines: readonly string[]; level: Level }) {
  const headingId = useId()
  if (lines.length === 0) return null
  const Heading = HEADINGS[level]
  return (
    <section className={styles['sec']} aria-labelledby={headingId}>
      <Heading id={headingId}>Not checked</Heading>
      <ul className={styles['unchecked']}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  )
}

/** One write, exactly as the request holds it: where it goes, then every field it carries, so nothing written is hidden. */
function Change({ action }: { action: ApprovalActionView }) {
  return (
    <dl className={styles['chg']}>
      <div>
        <dt>Where</dt>
        <dd>{whereWords(action)}</dd>
      </div>
      {fieldRows(action.fields).map(({ key, label, value }) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd className={key === 'body' ? styles['chgBody'] : undefined}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

interface DeclineReasonsProps {
  readonly reasons: readonly string[]
  readonly requester: string
  readonly picked: string | null
  readonly pending: boolean
  readonly busy: boolean
  readonly onPick: (reason: string) => void
  readonly onDecline: () => void
  readonly onBack: () => void
}

/**
 * Decline asks why, with a few quick reasons, and needs none. The reason is a note on the record. It adds no way to approve, and
 * the platform decides the decline the same with or without it. The second Decline is the confirmation.
 */
export function DeclineReasons({ reasons, requester, picked, pending, busy, onPick, onDecline, onBack }: DeclineReasonsProps) {
  const first = useRef<HTMLButtonElement>(null)
  const askId = useId()
  useEffect(() => first.current?.focus(), [])
  return (
    <div className={styles['decide']} role="group" aria-labelledby={askId}>
      <p id={askId}>
        <b>Why?</b> <span className={styles['muted']}>Optional. {requester} will see it.</span>
      </p>
      <div className={styles['picks']}>
        {reasons.map((reason, index) => (
          <button key={reason} ref={index === 0 ? first : undefined} type="button" className={styles['pick']} aria-pressed={picked === reason} onClick={() => onPick(reason)}>
            {picked === reason ? <IconCheck size={14} /> : null}
            {reason}
          </button>
        ))}
      </div>
      <div className={cx(styles['buttons'], styles['end'])}>
        <Button disabled={busy} onClick={onBack}>
          Back
        </Button>
        <Button variant="danger-outline" loading={pending} disabled={busy && !pending} onClick={onDecline}>
          Decline
        </Button>
      </div>
    </div>
  )
}

/** What only the page adds: the agents' summary, which helps the reader and is never the check. */
export interface PageDetails {
  /** What the agents found. The activity keeps it after the approval stops carrying it. */
  readonly found: string
}

export interface ApprovalGateProps {
  readonly approval: ApprovalView
  /**
   * Null in the side panel, which shows everything that will be written and the decision, and leaves the rest for the page. On the
   * run page the head's one pill speaks for the request, so the request draws none.
   */
  readonly page: PageDetails | null
  readonly decision: Pick<Decision, 'pending' | 'recorded' | 'steps' | 'error' | 'decide'>
  /** The run, for what happened after the yes. Null where the run isn't read. */
  readonly facts: StageFacts | null
  /** What the run didn't check, from notCheckedWords in decision.ts. Information for the reader, never the check. */
  readonly notChecked: readonly string[]
  /** The quick reasons Decline offers, from declineReasons in decision.ts. */
  readonly reasons: readonly string[]
  /** Who sees the reason with the record, and answers questions, by name. */
  readonly requester: string
  readonly questions: Questions
  readonly me: string | undefined
  readonly party: Party | null
  readonly nameOf: NameOf
  /** What happens after a decline, from declinedNext in words.ts. */
  readonly next: string | null
  readonly now: Date
}

/** Under the record, the Ask box or Decline's reasons open in place of the buttons. Never both. */
type Opened = { readonly kind: 'decline'; readonly picked: string | null } | { readonly kind: 'ask' }

/** The record once the request is decided or over, with a stamp once the write is made. */
function Record({ standing, words, facts, next }: { standing: Standing; words: string; facts: StageFacts | null; next: string | null }) {
  const made = standing.is === 'approved' && facts?.state === 'succeeded' && facts.count > 0
  return (
    <>
      <p className={cx(styles['record'], standing.is === 'approved' && styles['okRecord'], made && styles['stamped'])}>
        {standing.is === 'approved' ? <IconCheck size={16} /> : null}
        <span>{words}</span>
        {made ? (
          <span className={styles['stamp']} aria-hidden="true">
            {facts.tickets ? 'Created' : 'Written'}
          </span>
        ) : null}
      </p>
      {standing.is === 'declined' && next ? <p className={styles['muted']}>{next}</p> : null}
    </>
  )
}

/**
 * The request in the sketch's shape: whose workflow asks, exactly what will be written from the request's own records, what the
 * run didn't check, then the decision. The page adds the agents' summary, labelled as help, and why this person may decide. The
 * platform checks the digest and the deciding person again at the write, so nothing here is the check.
 */
export function ApprovalGate({ approval, page, decision, facts, notChecked, reasons, requester, questions, me, party, nameOf, next, now }: ApprovalGateProps) {
  const steps = decision.steps ?? approval.steps
  const standing = standingOf(steps)
  const canDecide = canDecideNow(approval, decision)
  // Once this person's decision is recorded, the request offers them nothing more, though the next read may take a while to say so.
  const whyNot = decision.recorded === null ? approval.why_not : 'decided_earlier_step'
  const busy = decision.pending !== null
  const [opened, setOpened] = useState<Opened | null>(null)
  const declineButton = useRef<HTMLButtonElement>(null)
  const askButton = useRef<HTMLButtonElement>(null)
  const backTo = useRef<Opened['kind'] | null>(null)
  const thread = useFocusAfter<HTMLHeadingElement>()
  const titleId = useId()
  useEffect(() => {
    if (opened !== null || backTo.current === null) return
    const to = backTo.current === 'ask' ? askButton : declineButton
    backTo.current = null
    to.current?.focus()
  }, [opened])

  const level: Level = page ? 2 : 3
  const Title = HEADINGS[level]
  const Section = HEADINGS[(level + 1) as Level]
  const pill = approvalPill(standing, canDecide)
  const turn = turnWords(standing, nameOf)
  const record = recordWords(standing, facts, nameOf, reasons, now)
  const sent = sentRowWords(steps, now)
  const projects = approval.actions.flatMap((action) => (typeof action.target['project'] === 'string' ? [action.target['project']] : []))
  const declining = opened?.kind === 'decline' ? opened : null

  return (
    <section className={styles['approval']} aria-labelledby={titleId}>
      <div className={styles['apprHead']}>
        <div>
          <p className={pills['kind']}>{kindWords(approval, nameOf)}</p>
          <Title id={titleId}>{approvalTitle(approval.actions)}</Title>
        </div>
        {page ? null : (
          <span className={cx(pills['pill'], pills[pill.tone])} data-approval-pill>
            {pill.label}
          </span>
        )}
      </div>
      {turn ? <p className={styles['turn']}>{turn}</p> : null}
      <section className={styles['sec']} aria-labelledby={`${titleId}-w`}>
        <Section id={`${titleId}-w`}>What will be written</Section>
        {approval.actions.map((action, index) => (
          <Change key={index} action={action} />
        ))}
      </section>
      <NotChecked lines={notChecked} level={(level + 1) as Level} />
      {page && page.found !== '' ? (
        <p className={styles['aiSum']}>
          <b>Summary by AI.</b> <TicketKeys text={page.found} keys={ticketKeysIn(page.found, projects)} /> Decide on the change above, not this.
        </p>
      ) : null}
      {page && standing.is === 'open' ? (
        <dl className={styles['chg']}>
          {sent ? (
            <div>
              <dt>Sent</dt>
              <dd>{sent}</dd>
            </div>
          ) : null}
          <div>
            <dt>{canDecide ? 'Why you' : 'Why not you'}</dt>
            <dd>{canDecide ? whyYouWords(standing) : lockWords(whyNot, party)}</dd>
          </div>
        </dl>
      ) : null}
      <QuestionThread approval={approval} me={me} nameOf={nameOf} answer={questions.answer} heading={thread} level={(level + 1) as Level} />
      <div className={styles['apprFoot']}>
        {record !== null ? (
          <Record standing={standing} words={record} facts={facts} next={next} />
        ) : !canDecide ? (
          <p className={styles['waitLine']}>
            <IconLock size={18} />
            <span>{waitingWords(whyNot, page === null)}</span>
          </p>
        ) : declining ? (
          <DeclineReasons
            reasons={reasons}
            requester={requester}
            picked={declining.picked}
            pending={decision.pending === 'decline'}
            busy={busy}
            onPick={(reason) => setOpened({ kind: 'decline', picked: declining.picked === reason ? null : reason })}
            onDecline={() => decision.decide({ verdict: 'decline', reason: declining.picked })}
            onBack={() => {
              backTo.current = 'decline'
              setOpened(null)
            }}
          />
        ) : opened?.kind === 'ask' ? (
          <AskBox
            requester={requester}
            ask={questions.ask}
            onSent={() => {
              thread.request()
              setOpened(null)
            }}
            onCancel={() => {
              backTo.current = 'ask'
              setOpened(null)
            }}
          />
        ) : (
          <>
            <Button ref={askButton} disabled={busy} onClick={() => setOpened({ kind: 'ask' })}>
              Ask {requester}
            </Button>
            <span className={cx(styles['buttons'], styles['end'])}>
              <Button variant="primary" loading={decision.pending === 'approve'} disabled={busy && decision.pending !== 'approve'} onClick={() => decision.decide(APPROVE)}>
                Approve
              </Button>
              <Button ref={declineButton} disabled={busy} onClick={() => setOpened({ kind: 'decline', picked: null })}>
                Decline
              </Button>
            </span>
          </>
        )}
      </div>
      {decision.error ? (
        <p className={styles['error']} role="alert">
          {decision.error}
        </p>
      ) : null}
    </section>
  )
}
