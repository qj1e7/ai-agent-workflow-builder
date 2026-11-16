import { useMemo } from 'react'
import { useUseCases, useWatchlist } from '../../api/queries'
import type { FreeReply, UseCaseView, WatchedSoftwareView } from '../../api/types'
import { Card } from '../../ui/Card'
import { REFRESH_MS as WATCH_REFRESH } from '../software/software'
import { REFRESH_MS } from '../workflows/workflow'
import { SoftwareRows, WorkflowRows } from './panels/ListRows'

type About = FreeReply['about'][number]

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

/** The live rows the names hold, each once and in the order the list keeps. A name nothing holds any more draws nothing. */
function held<T extends { name: string }>(live: readonly T[], names: readonly string[]): T[] {
  return live.filter((row) => names.some((name) => same(name, row.name)))
}

function AboutSoftware({ names, now }: { names: readonly string[]; now: Date }) {
  const watchlist = useWatchlist({ poll: WATCH_REFRESH })
  const view = watchlist.data
  const rows = useMemo<WatchedSoftwareView[]>(() => (view ? held(view.software, names) : []), [view, names])
  if (!view || rows.length === 0) return null
  return (
    <Card title="On your watchlist">
      <SoftwareRows rows={rows} view={view} label="Software the reply names" now={now} />
    </Card>
  )
}

function AboutWorkflows({ names, now }: { names: readonly string[]; now: Date }) {
  const useCases = useUseCases({ poll: REFRESH_MS })
  const rows = useMemo<UseCaseView[]>(() => (useCases.data ? held(useCases.data, names) : []), [useCases.data, names])
  if (rows.length === 0) return null
  return (
    <Card title="Workflows">
      <WorkflowRows useCases={rows} label="Workflows the reply names" now={now} />
    </Card>
  )
}

/**
 * The state line of each watched software and workflow a free reply names (ADR 0049). The version, the state and the last run
 * are read from the same live data as the Software and Workflows pages, never from the model's words. The rows are read-only
 * and open the item, so every role sees them.
 */
export function AboutRows({ about, now }: { about: readonly About[]; now: Date }) {
  const software = useMemo(() => about.filter((entry) => entry.section === 'watchlist').map((entry) => entry.name), [about])
  const workflows = useMemo(() => about.filter((entry) => entry.section === 'workflows').map((entry) => entry.name), [about])
  return (
    <>
      {software.length > 0 ? <AboutSoftware names={software} now={now} /> : null}
      {workflows.length > 0 ? <AboutWorkflows names={workflows} now={now} /> : null}
    </>
  )
}
