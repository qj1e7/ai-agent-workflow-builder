import { useState } from 'react'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useApproval, useRuns, useTeamsMessages } from '../../api/queries'
import type { RunView, TeamsStubMessage } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { IconCheck, IconClock, IconReplay, IconX, PortalMark, type Icon } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { Pill, type PillTone } from '../../ui/StatusPill'
import { channelsOf, chosenChannel, messagesIn } from './channels'
import { startedWords } from './startedWords'
import { standingOf, type StandingKind } from './standing'
import styles from './TeamsPage.module.css'

export function TeamsPage() {
  const messages = useTeamsMessages({ poll: true })
  const runs = useRuns({ poll: true })
  const [wanted, setWanted] = useState<string | null>(null)

  return (
    <div className="page">
      <PageHeader title="Teams">A stand-in for Microsoft Teams. Approval requests arrive here.</PageHeader>
      <div className={styles['window']}>
        {messages.data ? (
          <Inbox messages={messages.data} runs={runs.data ?? []} wanted={wanted} onChoose={setWanted} />
        ) : (
          <div className={styles['single']}>
            {messages.isError ? (
              <div className={styles['problem']}>
                <InlineMessage tone="error">We could not load the messages. {errorWords(messages.error)}</InlineMessage>
                <Button icon={IconReplay} loading={messages.isFetching} onClick={() => void messages.refetch()}>
                  Try again
                </Button>
              </div>
            ) : (
              <Skeleton lines={4} label="Loading messages" />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

interface InboxProps {
  messages: readonly TeamsStubMessage[]
  runs: readonly RunView[]
  wanted: string | null
  onChoose: (channel: string) => void
}

function Inbox({ messages, runs, wanted, onChoose }: InboxProps) {
  const channels = channelsOf(messages)
  const open = chosenChannel(channels, wanted)

  if (open === null) {
    return (
      <div className={styles['single']}>
        <EmptyState title="No messages yet." action={<ButtonLink to="/builder">Open the builder</ButtonLink>}>
          An approval request appears here.
        </EmptyState>
      </div>
    )
  }

  return (
    <>
      <nav className={styles['channels']} aria-label="Channels">
        <ul>
          {channels.map((channel) => (
            <li key={channel.name}>
              <button
                type="button"
                className={styles['channel']}
                aria-current={channel.name === open ? 'true' : undefined}
                onClick={() => onChoose(channel.name)}
              >
                <span>{channel.name}</span>
                <span className={styles['count']}>
                  {channel.count}
                  <span className="visually-hidden"> {channel.count === 1 ? 'message' : 'messages'}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <section className={styles['pane']} aria-labelledby="channel-heading">
        <header className={styles['paneHeader']}>
          <h2 id="channel-heading">{open}</h2>
        </header>
        <ol className={styles['thread']}>
          {messagesIn(messages, open).map((message) => (
            <li key={message.id}>
              <Message message={message} run={runs.find((each) => each.run_id === message.run_id)} />
            </li>
          ))}
        </ol>
      </section>
    </>
  )
}

const standingLook: Record<StandingKind, { tone: PillTone; icon: Icon }> = {
  waiting: { tone: 'waiting', icon: IconClock },
  approved: { tone: 'done', icon: IconCheck },
  declined: { tone: 'neutral', icon: IconX },
}

function Message({ message, run }: { message: TeamsStubMessage; run: RunView | undefined }) {
  const nameOf = useDisplayName()
  const approval = useApproval(message.approval_id, { poll: true })
  const standing = approval.data ? standingOf(approval.data.steps, nameOf) : null
  const look = standing ? standingLook[standing.kind] : null

  return (
    <article className={styles['message']}>
      <span className={styles['sender']} aria-hidden="true">
        <PortalMark size={22} />
      </span>
      <div className={styles['content']}>
        <header className={styles['from']}>
          <strong>AI workflow builder</strong>
          <time dateTime={message.ts}>{formatDayAndTime(message.ts)}</time>
        </header>
        <div className={styles['card']}>
          {run ? (
            <p className={styles['run']}>
              <strong>{run.use_case_name}</strong>
              <span>
                Started by {nameOf(run.started_by)}, {startedWords(run.started_at)}
              </span>
            </p>
          ) : null}
          <p>{message.text}</p>
          <div className={styles['standing']} aria-live="polite">
            {standing && look ? (
              <>
                <Pill tone={look.tone} icon={look.icon}>
                  {standing.headline}
                </Pill>
                {standing.detail ? <span className={styles['detail']}>{standing.detail}</span> : null}
              </>
            ) : approval.isError ? (
              <span className={styles['detail']}>We could not check the approval.</span>
            ) : (
              <span className={styles['detail']}>Checking the approval.</span>
            )}
          </div>
          <div className={styles['actions']}>
            <ButtonLink to={message.link}>Open the approval page</ButtonLink>
            <ButtonLink to={`/runs/${message.run_id}`}>Watch the run</ButtonLink>
          </div>
        </div>
      </div>
    </article>
  )
}
