import { useQueries } from '@tanstack/react-query'
import { useApiClient, useCacheScope } from '../../api/context'
import { useDisplayName } from '../../api/people'
import { fetchEventPage, keys } from '../../api/queries'
import type { StepDraw } from '../../ui/StepLine'
import { stepsOfRun, type Tile } from './boardTiles'

const STALE_MS = 30_000

/**
 * Each tile's last run as steps, read from the run's own events through the query client, so a run the page already read costs
 * nothing. A tile whose run can't be read has no entry, and draws no line.
 */
export function useBoardSteps(tiles: readonly Tile[]): ReadonlyMap<string, readonly StepDraw[]> {
  const client = useApiClient()
  const user = useCacheScope()
  const nameOf = useDisplayName()
  const reading = tiles.flatMap((tile) => (tile.lastRunId && tile.useCase.last_run ? [{ tile, runId: tile.lastRunId, state: tile.useCase.last_run.state }] : []))
  const results = useQueries({
    queries: reading.map(({ runId, state }) => ({
      queryKey: keys.runSteps(user, runId, state),
      queryFn: async () => (await fetchEventPage(client, runId)).events,
      staleTime: STALE_MS,
      retry: false,
    })),
  })
  const steps = new Map<string, readonly StepDraw[]>()
  reading.forEach(({ tile, runId }, index) => {
    const events = results[index]?.data
    if (!events) return
    const drawn = stepsOfRun(events, runId, tile.useCase, nameOf)
    if (drawn.length > 0) steps.set(tile.useCase.use_case_id, drawn)
  })
  return steps
}
