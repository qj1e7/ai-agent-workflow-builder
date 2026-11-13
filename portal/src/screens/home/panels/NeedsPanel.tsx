import { useMemo } from 'react'
import { useHome } from '../../../api/homeQueries'
import { Button } from '../../../ui/Button'
import { NeedRows } from '../NeedsSection'
import { needsOf } from '../home'
import { NeedsMore } from './NeedsMore'
import styles from './Lists.module.css'

/** Needs you in the panel (the sketch's `needs` view): the same Do now and Set up rows as on Home, every one the platform returned. */
export function NeedsPanel({ now }: { now: Date }) {
  const home = useHome()
  const needs = useMemo(() => (home.data ? needsOf(home.data) : null), [home.data])
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
  return <NeedRows needs={needs.shown} now={now} more={<NeedsMore needs={needs} />} />
}
