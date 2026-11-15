import type { Pager } from '../../../api/homeQueries'
import { ShowMore } from '../../../ui/ShowMore'
import { drawnKeys, type Needs } from '../home'

/** Show more under Needs you: the platform's next page of what needs the person joins the same rows, so every one counted can be opened. */
export function NeedsMore({ needs, pager }: { needs: Needs; pager: Pager }) {
  return <ShowMore shown={needs.shown.length} total={needs.total} pager={pager} keys={drawnKeys(needs.shown)} rowAttr="data-home-item" />
}
