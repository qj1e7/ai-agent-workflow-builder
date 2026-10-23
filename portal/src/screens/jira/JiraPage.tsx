import { useErrorWords } from '../../api/context'
import { useMockJiraTickets } from '../../api/queries'
import type { MockJiraTicket } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { IconReplay, IconTicket } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import styles from './JiraPage.module.css'

export function JiraPage() {
  const explain = useErrorWords()
  const tickets = useMockJiraTickets({ poll: true })

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
              <Ticket ticket={ticket} />
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

function Ticket({ ticket }: { ticket: MockJiraTicket }) {
  return (
    <article className={styles['ticket']}>
      <span className={styles['key']}>
        <IconTicket size={16} />
        {ticket.key}
      </span>
      <div className={styles['what']}>
        <h2>{ticket.title}</h2>
        <p className={styles['body']}>{ticket.body}</p>
      </div>
      <div className={styles['side']}>
        <p className={styles['created']}>
          Created <time dateTime={ticket.created_at}>{formatDayAndTime(ticket.created_at)}</time>
        </p>
        <ButtonLink to={`/runs/${ticket.run_id}`}>Watch the run</ButtonLink>
      </div>
    </article>
  )
}
