import { useId, type ReactNode } from 'react'
import { isOperator } from '../../api/me'
import { useMe, useUseCases } from '../../api/queries'
import type { HomeOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { FROM_LIST } from '../../ui/fromList'
import { Link } from '../../ui/Link'
import { OpenLink } from '../../ui/OpenItem'
import { StepLine, type StepDraw } from '../../ui/StepLine'
import { StatusPills } from '../workflows/Status'
import { REFRESH_MS, workflowPath } from '../workflows/workflow'
import { boardOf, type Board } from './boardTiles'
import { needsTotal } from './home'
import { useBoardSteps } from './useBoardSteps'
import styles from './SlimList.module.css'

interface SlimListProps {
  readonly board: Board
  /** Each workflow's last run as steps, for the ones whose run could be read. */
  readonly steps: ReadonlyMap<string, readonly StepDraw[]>
  /** The platform's Needs you count. */
  readonly needs: number
  readonly operator: boolean
  /** Why the workflows are missing, when they could not be loaded. */
  readonly problem?: ReactNode
}

/**
 * The glance beside the chat (the sketch's slim list): the Needs you count, which opens Needs you beside the chat, then each workflow as
 * its name, its one pill and the small step line of its last run. The full tiles stay on Home's board. The same words and pills as the board.
 */
export function SlimList({ board, steps, needs, operator, problem }: SlimListProps) {
  const label = operator ? 'Your workflows' : 'Workflows'
  const count = <span className={needs > 0 ? styles['alert'] : styles['count']}>{needs}</span>
  return (
    <aside className={styles['slim']} aria-label={label}>
      {needs > 0 ? (
        <OpenLink item={{ kind: 'needs' }} to="/workflows" className={styles['needs']}>
          Needs you {count}
        </OpenLink>
      ) : (
        <p className={styles['needs']}>Needs you {count}</p>
      )}
      {problem}
      {board.tiles.length > 0 ? (
        <ul className={styles['rows']}>
          {board.tiles.map(({ useCase }) => (
            <WorkflowRow key={useCase.use_case_id} useCase={useCase} steps={steps.get(useCase.use_case_id)} />
          ))}
        </ul>
      ) : null}
      <Link to="/workflows" className={styles['see']}>
        See all
      </Link>
    </aside>
  )
}

function WorkflowRow({ useCase, steps }: { useCase: Board['tiles'][number]['useCase']; steps: readonly StepDraw[] | undefined }) {
  const id = useId()
  return (
    <li data-workflow-id={useCase.use_case_id}>
      <OpenLink item={{ kind: 'workflow', id: useCase.use_case_id }} to={workflowPath(useCase)} state={FROM_LIST} className={styles['row']} aria-labelledby={`${id}-name`}>
        <span className={styles['top']}>
          <b id={`${id}-name`} className={styles['name']}>
            {useCase.name}
          </b>
          <StatusPills useCase={useCase} />
        </span>
        {steps ? <StepLine steps={steps} label="Last run" size="sm" still /> : null}
      </OpenLink>
    </li>
  )
}

/** The slim list for Home's chat: the person's workflows and their last runs, read as the board reads them, so a run read once costs nothing twice. */
export function ChatSlimList({ home, now }: { home: HomeOut; now: Date }) {
  const operator = isOperator(useMe().data)
  const useCases = useUseCases({ poll: REFRESH_MS })
  const board = boardOf(useCases.data ?? [], now)
  const steps = useBoardSteps(board.tiles)
  const problem =
    useCases.isError && !useCases.data ? (
      <div role="alert" className={styles['problem']}>
        <p>The workflows could not be loaded.</p>
        <Button onClick={() => void useCases.refetch()}>Try again</Button>
      </div>
    ) : null
  return <SlimList board={board} steps={steps} needs={needsTotal(home)} operator={operator} problem={problem} />
}
