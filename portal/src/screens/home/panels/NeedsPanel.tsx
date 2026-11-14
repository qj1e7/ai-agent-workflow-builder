import { useHome } from '../../../api/homeQueries'
import { Button } from '../../../ui/Button'
import { NeedRows } from '../NeedsSection'
import { usePagedNeeds } from '../usePagedNeeds'
import { NeedsMore } from './NeedsMore'
import styles from './Lists.module.css'

/** Needs you in the panel (the sketch's `needs` view), where the strip's “N more” leads: the same Do now and Set up rows as on Home, every one, a page at a time. */
export function NeedsPanel({ now }: { now: Date }) {
  const home = useHome()
  const { needs, pager } = usePagedNeeds(home.data)
  if (!needs) {
    return home.isError ? (
      <p role="alert">
        I couldn’t read what needs you just now. <Button onClick={() => void home.refetch()}>Try again</Button>
      </p>
    ) : (
      <p className="muted" role="status">
        Checking what needs you
      </p>
    )
  }
  if (needs.shown.length === 0) return <p className={styles['calm']}>Nothing needs you.</p>
  return <NeedRows needs={needs.shown} now={now} more={<NeedsMore needs={needs} pager={pager} />} />
}
