import { useId, type ReactNode } from 'react'
import { useDisplayName } from '../../api/people'
import { useUseCases } from '../../api/queries'
import { Button } from '../../ui/Button'
import { REFRESH_MS } from '../workflows/workflow'
import { Board, NextUp } from './Board'
import { boardOf, nextUp } from './boardTiles'
import type { Need } from './home'
import { NeedRows } from './NeedsSection'
import { useBoardSteps } from './useBoardSteps'
import styles from './Home.module.css'

export const NOTHING_NEEDS_YOU = 'Nothing needs you.'

interface HeroBoardProps {
  readonly needs: readonly Need[]
  readonly total: number
  /** What follows Needs you's tiles: the link to the rest, or Show more. */
  readonly more: ReactNode
  readonly now: Date
  /** An Approver's heading already counts what needs them, so Needs you carries no second count. An Operator's board is "Your workflows". An Approver's is "Workflows", and their heading already says whether anything needs them. */
  readonly operator: boolean
}

/** Needs you, as bright tiles, or the one line that says nothing needs the person, then the board of workflows. */
export function HeroBoard({ needs, total, more, now, operator }: HeroBoardProps) {
  const useCases = useUseCases({ poll: REFRESH_MS })
  const nameOf = useDisplayName()
  const listed = useCases.data ?? []
  const board = boardOf(listed, now)
  const steps = useBoardSteps(board.tiles)
  const headingId = useId()
  return (
    <>
      {needs.length > 0 ? (
        <section className={styles['block']} aria-labelledby={headingId}>
          <h2 id={headingId} className={styles['blockHead']}>
            Needs you {operator ? <span className={styles['blockCount']}>{total}</span> : null}
          </h2>
          <NeedRows needs={needs} now={now} level={3} tiles more={more} />
        </section>
      ) : useCases.data ? (
        <NextUp title={operator ? NOTHING_NEEDS_YOU : null} next={nextUp(listed, now)} />
      ) : null}
      {useCases.isError && !useCases.data ? (
        <div role="alert" className={styles['blockHead']}>
          <p>The workflows could not be loaded.</p>
          <Button onClick={() => void useCases.refetch()}>Try again</Button>
        </div>
      ) : (
        <Board board={board} steps={steps} now={now} heading={operator ? 'Your workflows' : 'Workflows'} nameOf={nameOf} />
      )}
    </>
  )
}
