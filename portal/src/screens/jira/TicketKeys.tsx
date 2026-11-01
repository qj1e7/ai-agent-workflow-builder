import { Link } from 'react-router'
import { useJiraBrowseUrl } from '../../api/ticketLinks'
import { IconExternal } from '../../ui/icons'
import { splitKeys, ticketHref } from './tickets'

/** A ticket key as a link. Every ticket key in the app goes through here, so ticketHref is the only place that picks where it leads. */
export function TicketLink({ ticketKey, className }: { ticketKey: string; className?: string }) {
  const { href, external } = ticketHref(ticketKey, useJiraBrowseUrl())
  if (!external) {
    return (
      <Link to={href} className={className}>
        {ticketKey}
      </Link>
    )
  }
  return (
    <a href={href} className={className} target="_blank" rel="noopener noreferrer">
      {ticketKey}
      <IconExternal size={12} />
      <span className="visually-hidden"> (opens Jira in a new tab)</span>
    </a>
  )
}

/** Words that may hold ticket keys, such as "Created MOCK-142 in Jira.", with each key as a link. */
export function TicketKeys({ text }: { text: string }) {
  return <>{splitKeys(text).map((piece, index) => (piece.key ? <TicketLink key={index} ticketKey={piece.text} /> : piece.text))}</>
}
