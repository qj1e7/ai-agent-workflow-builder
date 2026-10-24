import { useErrorWords } from '../../api/context'
import { useMarkDone, useMe, useMockJiraTickets } from '../../api/queries'
import type { JiraTicketStatus, MockJiraTicket } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { IconCheck, IconRing, IconReplay, IconTicket, type Icon } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { Pill, type PillTone } from '../../ui/StatusPill'
import styles from './JiraPage.module.css'

const STATUS_LOOK: Readonly<Record<JiraTicketStatus, { tone: PillTone; icon: Icon }>> = {
  'To Do': { tone: 'neutral', icon: IconRing },
  Done: { tone: 'done', icon: IconCheck },
}

export function JiraPage() {
  const explain = useErrorWords()
  const tickets = useMockJiraTickets({ poll: true })
  const operator = useMe().data?.roles.includes('operator') ?? false

  return (
    <div className="page">
      <PageHeader title="Mock Jira, project MOCK">Approved tickets are written here. This is not a real Jira project.</PageHeader>
      {tickets.data && tickets.data.length === 0 ? (
        <EmptyState title="No tickets yet." action={<ButtonLink to="/approvals">See approvals</ButtonLink>}>
          Nothing has been written yet.
        </EmptyState>
      ) : null}
      {tickets.data && tickets.data.length > 0 ? (
        <ul className={`panel ${styles['list']}`}>
          {tickets.data.map((ticket) => (
            <li key={ticket.key}>
              <Ticket ticket={ticket} operator={operator} />
            </li>
          ))}
        </ul>
      ) : null}
      {!tickets.data && tickets.isError ? (
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load the tickets. {explain(tickets.error)}</InlineMessage>
          <Button icon={IconReplay} loading={tickets.isFetching} onClick={() => void tickets.refetch()}>
            Try again
          </Button>
        </div>
      ) : null}
      {!tickets.data && !tickets.isError ? (
        <div className={`panel ${styles['padded']}`}>
          <Skeleton lines={4} label="Loading tickets" />
        </div>
      ) : null}
    </div>
  )
}

function Ticket({ ticket, operator }: { ticket: MockJiraTicket; operator: boolean }) {
  const explain = useErrorWords()
  const markDone = useMarkDone()
  const look = STATUS_LOOK[ticket.status]
  return (
    <article className={styles['ticket']} aria-labelledby={`${ticket.key}-title`}>
      <div className={styles['head']}>
        <span className={styles['key']}>
          <IconTicket size={16} />
          {ticket.key}
        </span>
        <Pill tone={look.tone} icon={look.icon}>
          {ticket.status}
        </Pill>
      </div>
      <div className={styles['what']}>
        <h2 id={`${ticket.key}-title`}>{ticket.title}</h2>
        <p className={styles['body']}>{ticket.body}</p>
      </div>
      <div className={styles['side']}>
        <p className={styles['created']}>
          Created <time dateTime={ticket.created_at}>{formatDayAndTime(ticket.created_at)}</time>
          {ticket.done_at ? (
            <>
              <br />
              Done <time dateTime={ticket.done_at}>{formatDayAndTime(ticket.done_at)}</time>
            </>
          ) : null}
        </p>
        {operator && ticket.status === 'To Do' ? (
          <Button
            icon={IconCheck}
            loading={markDone.isPending}
            onClick={() => markDone.mutate(ticket.key)}
          >
            Mark Done<span className="visually-hidden">: {ticket.key}</span>
          </Button>
        ) : null}
        <ButtonLink to={`/runs/${ticket.run_id}`}>Watch the run</ButtonLink>
        {markDone.isError ? <InlineMessage tone="error">{explain(markDone.error)}</InlineMessage> : null}
      </div>
    </article>
  )
}
