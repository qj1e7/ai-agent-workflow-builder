import { useWatchlist } from '../../api/queries'
import { countLine, REFRESH_MS } from './software'

/** The count line under the Software watchlist's title, from the query the page's rows come from. The lead stands in until it loads, and for an empty list. */
export function WatchLine({ lead }: { lead: string }) {
  const rows = useWatchlist({ poll: REFRESH_MS }).data?.software
  const line = rows ? countLine(rows) : null
  return <>{line ?? lead}</>
}
