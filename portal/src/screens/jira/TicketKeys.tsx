import { Link } from 'react-router'
import { useJiraBrowseUrl } from '../../api/ticketLinks'
import { IconExternal } from '../../ui/icons'
import { splitKeys, ticketHref } from './tickets'

/** A ticket key as a link. Every ticket key in the app goes through here, so ticketHref is the only place that picks where it leads. */
export function TicketLink({ ticketKey, className, href: given }: { ticketKey: string; className?: string; href?: string | null | undefined }) {
  const { href, external } = ticketHref(ticketKey, useJiraBrowseUrl(), given ?? null)
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
export function TicketKeys({ text, keys, hrefs }: { text: string; keys: readonly string[]; hrefs?: Readonly<Record<string, string>> | undefined }) {
  return <>{splitKeys(text, keys).map((piece, index) => (piece.key ? <TicketLink key={index} ticketKey={piece.text} href={hrefs?.[piece.text]} /> : piece.text))}</>
}
