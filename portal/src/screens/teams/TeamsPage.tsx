import { useState } from 'react'
import { errorWords } from '../../api/errors'
import { useTeamsMessages } from '../../api/queries'
import type { TeamsStubMessage } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { IconChat, IconReplay, PortalMark } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { channelsOf, chosenChannel, messagesIn } from './channels'
import styles from './TeamsPage.module.css'

export function TeamsPage() {
  const messages = useTeamsMessages({ poll: true })
  const [wanted, setWanted] = useState<string | null>(null)

  return (
    <div className="page">
      <PageHeader title="Teams">
        A stand-in for Microsoft Teams. Approval requests from the AI workflow builder arrive here, as they will in the real thing.
      </PageHeader>
      <div className={styles['window']}>
        {messages.data ? (
          <Inbox messages={messages.data} wanted={wanted} onChoose={setWanted} />
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
  wanted: string | null
  onChoose: (channel: string) => void
}

function Inbox({ messages, wanted, onChoose }: InboxProps) {
  const channels = channelsOf(messages)
  const open = chosenChannel(channels, wanted)

  if (open === null) {
    return (
      <div className={styles['single']}>
        <EmptyState
          title="No messages yet."
          action={<ButtonLink to="/builder">Open the builder</ButtonLink>}
        >
          A message appears here when a run asks an Approver for a decision.
        </EmptyState>
      </div>
    )
  }

  return (
    <>
      <nav className={styles['channels']} aria-label="Channels">
        <p className={styles['stub']}>
          <IconChat size={18} />
          Demo stub
        </p>
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
              <Message message={message} />
            </li>
          ))}
        </ol>
      </section>
    </>
  )
}

function Message({ message }: { message: TeamsStubMessage }) {
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
          <p>{message.text}</p>
          <ButtonLink to={message.link}>Open the approval page</ButtonLink>
        </div>
      </div>
    </article>
  )
}
