import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'
import { errorWords } from '../api/errors'
import { connectorLabel, objectNoun } from '../api/labels'
import { useRetry, useTroubleshoot } from '../api/queries'
import type { WriteActionView } from '../api/types'
import { teamsWords, type Gate, type PanelSpot } from '../run'
import type { Decision } from '../screens/approval/useDecision'
import { describeAction } from '../screens/approval/writeAction'
import { AgentFace } from '../ui/AgentFace'
import { agentIdentity } from '../ui/agents'
import { cx } from '../ui/cx'
import { InlineMessage, Skeleton } from '../ui/Feedback'
import { formatTime } from '../ui/format'
import { IconCheck, IconDoc, IconLock, IconReplay } from '../ui/icons'
import styles from './panels.module.css'

interface FrameProps {
  readonly tone: 'wait' | 'bad' | 'ok'
  readonly label: string
  /** Called when the panel leaves while it holds focus, so focus is never dropped on the page. */
  readonly onLeave: () => void
  readonly children: ReactNode
}

function Frame({ tone, label, onLeave, children }: FrameProps) {
  const frame = useRef<HTMLDivElement>(null)
  const leave = useRef(onLeave)
  useEffect(() => {
    leave.current = onLeave
  })
  useLayoutEffect(() => {
    const element = frame.current
    return () => {
      if (element?.contains(document.activeElement)) leave.current()
    }
  }, [])
  return (
    <div ref={frame} className={cx(styles['panel'], styles[tone])} role="region" aria-label={label}>
      {children}
    </div>
  )
}

interface ActionProps {
  readonly variant: 'primary' | 'quiet'
  readonly busy: boolean
  readonly onPress: () => void
  readonly children: ReactNode
}

/** aria-disabled rather than disabled, so focus stays on the button while the platform answers. */
function Action({ variant, busy, onPress, children }: ActionProps) {
  return (
    <button type="button" className={cx(styles['btn'], styles[variant])} aria-disabled={busy || undefined} onClick={() => (busy ? undefined : onPress())}>
      {children}
    </button>
  )
}

function headingOf(action: WriteActionView): string {
  const thing = [connectorLabel(action.connector), objectNoun(action.operation)].filter((word) => word !== '').join(' ')
  const project = action.target['project']
  return typeof project === 'string' && project !== '' ? `${thing} in ${project}` : thing
}

function paragraphs(body: string | null): string[] {
  return body ? body.split(/\n{2,}/) : []
}

const CONFLICT_WORDS = 'Another Approver decided this step first.'

interface ApprovalPanelProps {
  readonly decision: Decision
  readonly gate: Gate | null
  /** Approve and Decline act only on the newest frame of a run that is still waiting. */
  readonly atHead: boolean
  readonly onLeave: () => void
}

/** The proposed write under the barrier, and the decision in place: Approve and Decline, or the platform's reason this viewer cannot. */
export function ApprovalPanel({ decision, gate, atHead, onLeave }: ApprovalPanelProps) {
  const { view, state, sending, sent } = decision
  const panel = state?.panel
  const notice = state?.notice
  const busy = sending !== null || sent !== null
  const first = view?.actions[0]
  const teams = gate ? teamsWords(gate) : null
  return (
    <Frame tone="wait" label="Approval" onLeave={onLeave}>
      {view ? (
        <>
          {first ? <h3 className={styles['heading']}>{headingOf(first)}</h3> : null}
          {view.actions.map((action, index) => {
            const { title, body } = describeAction(action)
            return (
              <div key={index} className={styles['ticket']}>
                {title ? <b>{title}</b> : null}
                {paragraphs(body).map((words, at) => (
                  <p key={at}>{words}</p>
                ))}
              </div>
            )
          })}
        </>
      ) : decision.loadError ? (
        <InlineMessage tone="error">{errorWords(decision.loadError)}</InlineMessage>
      ) : (
        <Skeleton lines={3} label="Loading the request." />
      )}
      {notice ? <InlineMessage tone="error">{notice.kind === 'conflict' ? CONFLICT_WORDS : notice.message}</InlineMessage> : null}
      {(atHead && panel?.kind === 'can_decide') || busy ? (
        <div className={styles['acts']}>
          <Action variant="primary" busy={busy} onPress={() => decision.send('approve')}>
            <IconCheck strokeWidth={2.2} />
            Approve
          </Action>
          <Action variant="quiet" busy={busy} onPress={() => decision.send('decline')}>
            Decline
          </Action>
        </div>
      ) : null}
      {panel?.kind === 'cannot_decide' ? (
        <p className={styles['note']}>
          <IconLock strokeWidth={2.2} />
          <span>{panel.words}</span>
        </p>
      ) : null}
      {teams && gate?.link ? (
        <p className={styles['teams']}>
          {teams}. <Link to={gate.link}>Open the approval page</Link>
        </p>
      ) : null}
    </Frame>
  )
}

interface TroublePanelProps {
  readonly runId: string
  readonly spot: Extract<PanelSpot, { is: 'trouble' }>
  readonly atHead: boolean
  readonly onRetried: () => void
  readonly onLeave: () => void
}

/** Under the break: the AI troubleshooter's likely cause and suggestion, and Retry run when the platform allows it. */
export function TroublePanel({ runId, spot, atHead, onRetried, onLeave }: TroublePanelProps) {
  const advice = useTroubleshoot(runId, true, spot.attempt)
  const retry = useRetry(runId)
  const troubleshooter = agentIdentity('troubleshooter')
  return (
    <Frame tone="bad" label="AI troubleshooter advice" onLeave={onLeave}>
      <div className={styles['advisor']}>
        <AgentFace id={troubleshooter.id} size={44} />
        <b>{troubleshooter.name}</b>
      </div>
      {advice.data ? (
        <>
          <p className={styles['cause']}>{advice.data.advice.likely_cause}</p>
          <p className={styles['do']}>{advice.data.advice.suggestion}</p>
        </>
      ) : advice.isError ? (
        <InlineMessage tone="error">{errorWords(advice.error)}</InlineMessage>
      ) : (
        <Skeleton lines={2} label="Loading the advice." />
      )}
      {spot.retryable && atHead ? (
        <div className={styles['acts']}>
          <Action variant="primary" busy={retry.isPending || retry.isSuccess} onPress={() => retry.mutate(undefined, { onSuccess: onRetried })}>
            <IconReplay strokeWidth={2.2} />
            Retry run
          </Action>
        </div>
      ) : null}
      {retry.isError ? <InlineMessage tone="error">{errorWords(retry.error)}</InlineMessage> : null}
    </Frame>
  )
}

function names(list: readonly string[]): string {
  return list.length <= 1 ? (list[0] ?? '') : `${list.slice(0, -1).join(', ')} and ${list.at(-1) ?? ''}`
}

function createdWords(at: number | null, approvedBy: readonly string[]): string {
  const created = at === null ? 'Created' : `Created at ${formatTime(new Date(at).toISOString())}`
  return approvedBy.length > 0 ? `${created}, approved by ${names(approvedBy)}` : created
}

/** Under the last written stop: each written key, its title, and when and on whose approval it was created. */
export function WrittenPanel({ spot, onLeave }: { spot: Extract<PanelSpot, { is: 'written' }>; onLeave: () => void }) {
  return (
    <Frame tone="ok" label="Written" onLeave={onLeave}>
      {spot.lines.map((line) => (
        <div key={line.reference} className={styles['written']}>
          <p className={styles['key']}>
            <IconDoc strokeWidth={2.2} />
            <span>{line.reference}</span>
          </p>
          <b className={styles['title']}>{line.title}</b>
          <p className={styles['meta']}>{createdWords(line.at, spot.approvedBy)}</p>
        </div>
      ))}
    </Frame>
  )
}
