import type { UseCaseView } from '../../api/types'
import type { StepDraw } from '../../ui/StepLine'
import { emptyModel, foldWire, stationsOf } from '../run/runModel'
import { planOf } from '../run/useRunStory'
import { triggerWords, type NameOf } from '../run/words'
import { nextRunWords, statusOf } from '../workflows/workflow'

/**
 * How many tiles Home's board draws: two rows of three. Each tile reads its last run from the run's own events, so the board asks for
 * no more runs than it shows. The rest are one link away on Workflows, which counts them.
 */
export const BOARD_SHOWN = 6

export interface Tile {
  readonly useCase: UseCaseView
  /** When it runs next. Null unless the workflow is on, since a pill already says Paused or Draft. */
  readonly next: string | null
  /** The run its step line is read from. Null before its first run. */
  readonly lastRunId: string | null
}

export interface Board {
  readonly tiles: readonly Tile[]
  readonly total: number
}

/** The person's workflows, the ones that need them first, then as the platform lists them. */
export function boardOf(useCases: readonly UseCaseView[], now: Date): Board {
  const needs = (useCase: UseCaseView) => (statusOf(useCase).four === 'needs' ? 0 : 1)
  const sorted = useCases.map((useCase, index) => ({ useCase, index })).sort((a, b) => needs(a.useCase) - needs(b.useCase) || a.index - b.index)
  const tiles = sorted.slice(0, BOARD_SHOWN).map(({ useCase }): Tile => ({ useCase, next: useCase.state === 'on' ? nextRunWords(useCase, now) : null, lastRunId: useCase.last_run?.run_id ?? null }))
  return { tiles, total: useCases.length }
}

/** The workflow that runs soonest, for the line that says nothing needs the person. Null when none has a time. */
export function nextUp(useCases: readonly UseCaseView[], now: Date): { readonly name: string; readonly when: string } | null {
  const soonest = useCases
    .filter((useCase) => useCase.state === 'on' && useCase.next_run_at !== null)
    .sort((a, b) => Date.parse(a.next_run_at ?? '') - Date.parse(b.next_run_at ?? ''))[0]
  return soonest ? { name: soonest.name, when: nextRunWords(soonest, now) } : null
}

/**
 * A run's steps for the small step line, folded from its own events with the run page's own model, so a tile and the run page never
 * disagree. No events, no steps: the tile then draws no line.
 */
export function stepsOfRun(events: readonly unknown[], runId: string, useCase: UseCaseView, nameOf: NameOf): StepDraw[] {
  if (events.length === 0) return []
  const model = foldWire(emptyModel, events, runId)
  const trigger = triggerWords(model, useCase.schedule, nameOf, useCase.last_run?.at ?? '')
  return stationsOf(model, planOf(useCase), trigger).map((station) => ({ key: station.key, name: station.label, icon: station.icon, state: station.state }))
}

/** The runs the board reads, one per tile that has run, each with the state its read is keyed by. */
export function readsOf(tiles: readonly Tile[]): readonly { readonly tile: Tile; readonly runId: string; readonly state: string }[] {
  return tiles.slice(0, BOARD_SHOWN).flatMap((tile) => (tile.lastRunId && tile.useCase.last_run ? [{ tile, runId: tile.lastRunId, state: tile.useCase.last_run.state }] : []))
}
