import { useDisplayName } from '../../api/people'
import type { StepDraw } from '../../ui/StepLine'
import { useRunSteps } from '../run/useRunSteps'
import { readsOf, stepsOfRun, type Tile } from './boardTiles'

/**
 * Each tile's last run as steps, from the one per-run read the workflow page uses too. A tile whose run can't be read, or whose run has no
 * events, has no entry, and draws no line.
 */
export function useBoardSteps(tiles: readonly Tile[]): ReadonlyMap<string, readonly StepDraw[]> {
  const nameOf = useDisplayName()
  const reading = readsOf(tiles)
  const events = useRunSteps(reading.map(({ runId, state }) => ({ runId, version: state })))
  const steps = new Map<string, readonly StepDraw[]>()
  for (const { tile, runId } of reading) {
    const read = events.get(runId)
    if (!read) continue
    const drawn = stepsOfRun(read, runId, tile.useCase, nameOf)
    if (drawn.length > 0) steps.set(tile.useCase.use_case_id, drawn)
  }
  return steps
}
