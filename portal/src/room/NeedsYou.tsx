import { useState } from 'react'
import { failureStageLabel } from '../api/labels'
import { errorWords } from '../api/errors'
import { useRetry, useTroubleshoot } from '../api/queries'
import type { LiveView } from '../run'
import { Avatar } from '../ui/Avatar'
import { agentIdentity } from '../ui/agents'
import { Button, ButtonAnchor, ButtonLink } from '../ui/Button'
import { InlineMessage, Skeleton } from '../ui/Feedback'
import { formatDuration } from '../ui/format'
import { IconClock, IconFastForward, IconReplay, IconShield } from '../ui/icons'
import { STATUS_PAGES } from './registry'
import styles from './NeedsYou.module.css'

interface ActionCardProps {
  view: LiveView
}

/** The amber card at the approval pause: what waits, since when, who can decide, and where to go. */
export function ActionCard({ view }: ActionCardProps) {
  const { room, frame } = view
  const open = room.approval?.steps.find((step) => step.state.is === 'open')
  if (!room.approval || !open) return null
  const starter = room.starter?.display
  return (
    <section className={styles['card']} aria-labelledby="needs-you-title">
      <h2 id="needs-you-title" className={styles['title']}>
        <IconShield size={20} />
        The run is waiting for an Approver. Nothing has been written.
      </h2>
      <p className={styles['counter']}>
        <span className={styles['counterWords']}>
          <IconClock size={18} />
          {frame.waiting ? `Waiting ${formatDuration(frame.waiting.elapsedMs, { noWrap: true })}` : 'Waiting'}
        </span>
        {frame.spedUp ? (
          <span className={styles['spedUp']}>
            <IconFastForward size={12} />
            Sped up
          </span>
        ) : null}
      </p>
      <p className={styles['who']}>
        {open.label}.{starter ? ` Anyone except ${starter}.` : ''}
      </p>
      <div className={styles['buttons']}>
        <ButtonLink to={room.approval.link} variant="primary">
          Open the approval page
        </ButtonLink>
        <ButtonLink to="/teams">Open the Teams message</ButtonLink>
      </div>
    </section>
  )
}

interface TroubleshooterPanelProps {
  runId: string
  view: LiveView
}

/** The AI troubleshooter's advice after a failure, with Retry and the read door's status page. */
export function TroubleshooterPanel({ runId, view }: TroubleshooterPanelProps) {
  const { room } = view
  const failed = room.phase.name === 'failed' ? room.phase : null
  const advice = useTroubleshoot(runId, failed !== null)
  const retry = useRetry(runId)
  const [retried, setRetried] = useState(false)
  if (!failed) return null
  const stopped = room.agents.find((seat) => seat.status === 'stopped')
  const door = stopped ? agentIdentity(stopped.id).readDoor : undefined
  const statusPage = door ? STATUS_PAGES[door] : undefined
  const failedDoor = room.trips.some((trip) => trip.state === 'failed')

  function retryRun() {
    retry.mutate(undefined, {
      onSuccess: () => {
        setRetried(true)
        view.transport.reconnect()
      },
    })
  }

  return (
    <section className={styles['trouble']} aria-labelledby="trouble-title">
      <h2 id="trouble-title" className={styles['troubleTitle']}>
        <Avatar kind="agent" agentId="troubleshooter" size={28} />
        AI troubleshooter
      </h2>
      {advice.isPending ? <Skeleton lines={3} label="The AI troubleshooter is looking at the run." /> : null}
      {advice.isError ? <InlineMessage tone="error">{errorWords(advice.error)}</InlineMessage> : null}
      {advice.data ? (
        <div className={styles['advice']}>
          <p>
            <strong>{advice.data.advice.explanation}</strong>
          </p>
          <p>{advice.data.advice.likely_cause}</p>
          <p>{advice.data.advice.suggestion}</p>
        </div>
      ) : null}
      <dl className={styles['facts']}>
        <dt>Stopped</dt>
        <dd>{failureStageLabel[failed.stage] ?? failed.stage}</dd>
        <dt>Agent</dt>
        <dd>{stopped ? agentIdentity(stopped.id, stopped.display).name : 'Not an agent'}</dd>
        <dt>Safe to retry</dt>
        <dd>{failed.retryable ? 'Yes' : 'No'}</dd>
        <dt>Written</dt>
        <dd>Nothing</dd>
      </dl>
      <div className={styles['buttons']}>
        {failed.retryable ? (
          <Button variant="primary" icon={IconReplay} loading={retry.isPending} onClick={retryRun}>
            {retried ? 'Retrying' : 'Retry run'}
          </Button>
        ) : null}
        {statusPage && failedDoor ? <ButtonAnchor href={statusPage.href}>{statusPage.label}</ButtonAnchor> : null}
      </div>
      {retry.isError ? <InlineMessage tone="error">{errorWords(retry.error)}</InlineMessage> : null}
    </section>
  )
}
