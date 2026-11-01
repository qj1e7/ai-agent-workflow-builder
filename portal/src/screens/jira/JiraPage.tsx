import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useMarkDone, useMe, useMockJiraTickets } from '../../api/queries'
import type { MockJiraTicket } from '../../api/types'
import { Button } from '../../ui/Button'
import { useFocusWhenReady } from '../../ui/focus'
import { createdWords, detailsId, EMPTY_WORDS, LOAD_WORDS, missingWords, newestFirst, pressMarkDone, showMarkDone } from './tickets'
import styles from './Jira.module.css'

const STATUS_ID = 'jira-status'

interface RowProps {
  readonly ticket: MockJiraTicket
  readonly open: boolean
  readonly operator: boolean
  readonly marking: boolean
  readonly onToggle: () => void
  readonly onMarkDone: () => void
}

function TicketRow({ ticket, open, operator, marking, onToggle, onMarkDone }: RowProps) {
  const done = ticket.status === 'Done'
  const bodyId = `ticket-body-${ticket.key}`
  return (
    <li className={styles['row']} data-ticket={ticket.key} data-open={open || undefined}>
      <div className={styles['main']}>
        <h2>
          <span className={styles['key']}>{ticket.key}</span>
          {ticket.title}
        </h2>
        <div className={styles['meta']}>
          <span className={styles['pill']} data-done={done || undefined}>
            {ticket.status}
          </span>
          <span>{createdWords(ticket.created_at)}</span>
          <Link to={`/runs/${ticket.run_id}`}>
            See the run
            <span className="visually-hidden"> that created {ticket.key}</span>
          </Link>
        </div>
      </div>
      <div className={styles['acts']}>
        <Button id={detailsId(ticket.key)} aria-expanded={open} aria-controls={open ? bodyId : undefined} onClick={onToggle}>
          {open ? 'Hide details' : 'Details'}
          <span className="visually-hidden"> of {ticket.key}</span>
        </Button>
        {showMarkDone(ticket, operator) ? (
          <Button variant="primary" loading={marking} onClick={onMarkDone}>
            Mark done<span className="visually-hidden"> {ticket.key}</span>
          </Button>
        ) : null}
      </div>
      {open ? (
        <p className={styles['body']} id={bodyId}>
          {ticket.body}
        </p>
      ) : null}
    </li>
  )
}

interface LoadedProps {
  readonly tickets: readonly MockJiraTicket[]
  readonly operator: boolean
  readonly openKey: string | undefined
}

function Loaded({ tickets, operator, openKey }: LoadedProps) {
  const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set(openKey ? [openKey] : []))
  const [said, setSaid] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [marking, setMarking] = useState<string | null>(null)
  const [marked, setMarked] = useState<string | null>(null)
  const mark = useMarkDone()
  const latch = useLatch()
  const words = useErrorWords()
  const rows = newestFirst(tickets)
  const missing = openKey !== undefined && !tickets.some((ticket) => ticket.key === openKey)

  // After Mark done the button is gone, so focus moves to the same ticket's Details button once the row reads Done.
  const focusAfter = useFocusWhenReady(marked !== null && tickets.some((ticket) => ticket.key === marked && ticket.status === 'Done'), () =>
    document.getElementById(detailsId(marked ?? '')),
  )

  useEffect(() => {
    if (openKey) document.querySelector(`[data-ticket="${CSS.escape(openKey)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [openKey])

  function press(key: string) {
    pressMarkDone(
      latch,
      (ticketKey, outcome) => mark.mutate(ticketKey, outcome),
      key,
      {
        start: () => {
          setProblem(null)
          setSaid('')
          setMarking(key)
        },
        armFocus: () => {
          setMarked(key)
          focusAfter()
        },
        done: setSaid,
        fail: setProblem,
        settled: () => setMarking(null),
      },
      words,
    )
  }

  return (
    <>
      <p className={styles['status']} id={STATUS_ID} role="status">
        {said || (missing && openKey ? missingWords(openKey) : '')}
      </p>
      {problem ? (
        <p className={styles['error']} role="alert">
          {problem}
        </p>
      ) : null}
      {rows.length === 0 ? (
        <div className={styles['empty']}>
          <b>No tickets</b>
          <span>{EMPTY_WORDS}</span>
        </div>
      ) : (
        <ul className={styles['list']} aria-label="Tickets, newest first">
          {rows.map((ticket) => (
            <TicketRow
              key={ticket.key}
              ticket={ticket}
              open={opened.has(ticket.key)}
              operator={operator}
              marking={marking === ticket.key}
              onToggle={() =>
                setOpened((before) => {
                  const next = new Set(before)
                  if (!next.delete(ticket.key)) next.add(ticket.key)
                  return next
                })
              }
              onMarkDone={() => press(ticket.key)}
            />
          ))}
        </ul>
      )}
    </>
  )
}

/** The practice Jira's tickets. /jira/:key opens that ticket. */
export function JiraRoute() {
  const { key } = useParams()
  const me = useMe()
  const tickets = useMockJiraTickets({ poll: 10_000 })
  if ((tickets.isError && !tickets.data) || me.isError) {
    return (
      <>
        <p className={styles['error']}>{LOAD_WORDS}</p>
        <Button onClick={() => void Promise.all([tickets.refetch(), me.refetch()])}>Try again</Button>
      </>
    )
  }
  if (!tickets.data || !me.data) {
    return (
      <>
        <p className="muted" role="status">
          Loading the tickets
        </p>
      </>
    )
  }
  return (
    <>
      <Loaded tickets={tickets.data} operator={me.data.roles.includes('operator')} openKey={key} />
    </>
  )
}
