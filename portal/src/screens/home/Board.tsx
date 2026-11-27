import { useId } from 'react'
import { Link } from '../../ui/Link'
import { IconCheck } from '../../ui/icons'
import { OpenLink } from '../../ui/OpenItem'
import { StepLine, type StepDraw } from '../../ui/StepLine'
import { FROM_LIST } from '../../ui/fromList'
import { StatusPills } from '../workflows/Status'
import { lastRunParts, NO_RUNS, workflowPath } from '../workflows/workflow'
import type { Board as BoardOf, Tile } from './boardTiles'
import styles from './Board.module.css'

interface TileProps {
  readonly tile: Tile
  readonly steps: readonly StepDraw[] | undefined
  readonly now: Date
  readonly nameOf: (id: string) => string
}

/**
 * One workflow as the sketch draws it: its name and its one pill, its last run as the small step line, then when it runs next and
 * when it last ran. The whole tile is one link. Why a workflow needs the person is said once, in Needs you, so a tile has only its pill.
 * With no step line, because the run could not be read, the tile says how the run went in words and draws no dots.
 */
function WorkflowTile({ tile, steps, now, nameOf }: TileProps) {
  const { useCase, next } = tile
  const ids = useId()
  const last = lastRunParts(useCase, now, nameOf)
  return (
    <li className={styles['cell']} data-workflow-id={useCase.use_case_id}>
      <OpenLink item={{ kind: 'workflow', id: useCase.use_case_id }} to={workflowPath(useCase)} state={FROM_LIST} className={styles['tile']} aria-labelledby={`${ids}-name`} aria-describedby={`${ids}-meta`}>
        <span className={styles['top']}>
          <b id={`${ids}-name`} className={styles['name']}>
            {useCase.name}
          </b>
          <StatusPills useCase={useCase} />
        </span>
        {steps ? <StepLine steps={steps} label="Last run" /> : null}
        <span id={`${ids}-meta`} className={styles['meta']}>
          {next !== null ? (
            <>
              <b>Next run</b>
              <span>{next}</span>
            </>
          ) : null}
          <b>Last run</b>
          <span>{last ? (steps ? last.when : `${last.when}: ${last.what}`) : NO_RUNS}</span>
        </span>
      </OpenLink>
    </li>
  )
}

interface BoardProps {
  readonly board: BoardOf
  /** Each tile's last run as steps, for the tiles whose run could be read. */
  readonly steps: ReadonlyMap<string, readonly StepDraw[]>
  readonly now: Date
  readonly heading: string
  readonly nameOf: (id: string) => string
}

/** The board under Needs you: the person's workflows as tiles. A count says how many there are, and a link goes to all of them. */
export function Board({ board, steps, now, heading, nameOf }: BoardProps) {
  const headingId = useId()
  if (board.total === 0) return null
  return (
    <section className={styles['board']} aria-labelledby={headingId}>
      <div className={styles['head']}>
        <h2 id={headingId}>
          {heading} <span className={styles['count']}>{board.total}</span>
        </h2>
        {board.total > board.tiles.length ? <Link to="/workflows">See all on Workflows</Link> : null}
      </div>
      <ul className={styles['tiles']} aria-label={heading}>
        {board.tiles.map((tile) => (
          <WorkflowTile key={tile.useCase.use_case_id} tile={tile} steps={steps.get(tile.useCase.use_case_id)} now={now} nameOf={nameOf} />
        ))}
      </ul>
    </section>
  )
}

interface NextUpProps {
  /** "Nothing needs you.", or null where the page's heading already says it. */
  readonly title: string | null
  readonly next: { readonly name: string; readonly when: string } | null
}

/** What Home says while nothing needs the person: one line, with the next run. */
export function NextUp({ title, next }: NextUpProps) {
  if (title === null && next === null) return null
  return (
    <div className={styles['pulse']}>
      {title !== null ? (
        <>
          <span className={styles['mark']} aria-hidden="true">
            <IconCheck />
          </span>
          <p className={styles['pulseTitle']}>{title}</p>
        </>
      ) : null}
      {next ? (
        <p className={styles['pulseNext']}>
          Next run
          <b>
            {next.name}, {next.when}
          </b>
        </p>
      ) : null}
    </div>
  )
}
