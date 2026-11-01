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

/** Words that hold ticket keys the Portal already knows, such as "Created OPS-142 in Jira.", with exactly those keys as links. */
export function TicketKeys({ text, keys }: { text: string; keys: readonly string[] }) {
  return <>{splitKeys(text, keys).map((piece, index) => (piece.key ? <TicketLink key={index} ticketKey={piece.text} /> : piece.text))}</>
}
