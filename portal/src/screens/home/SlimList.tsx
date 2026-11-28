import type { ReactNode } from 'react'
import { isOperator } from '../../api/me'
import { useMe, useUseCases } from '../../api/queries'
import type { HomeOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { FROM_LIST } from '../../ui/fromList'
import { Link } from '../../ui/Link'
import { OpenLink } from '../../ui/OpenItem'
import { StateMark } from '../../ui/StateMark'
import { statusPill } from '../workflows/Status'
import { REFRESH_MS, workflowPath } from '../workflows/workflow'
import { boardOf, type Board } from './boardTiles'
import { needsTotal } from './home'
import styles from './SlimList.module.css'

interface SlimListProps {
  readonly board: Board
  /** The platform's Needs you count. */
  readonly needs: number
  readonly operator: boolean
  /** Why the workflows are missing, when they could not be loaded. */
  readonly problem?: ReactNode
}

/**
 * The glance beside the chat (the sketch's slim list): the Needs you count, which opens Needs you beside the chat, then each workflow as
 * its state mark and its name, as the sketch draws it. The mark says the pill's words, so it reads no run. The full tiles stay on Home's board.
 */
export function SlimList({ board, needs, operator, problem }: SlimListProps) {
  const label = operator ? 'Your workflows' : 'Workflows'
  const count = <span className={needs > 0 ? styles['alert'] : styles['count']}>{needs}</span>
  return (
    <aside className={styles['slim']} aria-label="Needs you and your workflows">
      {needs > 0 ? (
        <OpenLink item={{ kind: 'needs' }} to="/workflows" className={styles['needs']}>
          Needs you {count}
        </OpenLink>
      ) : (
        <p className={styles['needs']}>Needs you {count}</p>
      )}
      {problem}
      {board.tiles.length > 0 ? (
        <ul className={styles['rows']} aria-label={label}>
          {board.tiles.map(({ useCase }) => (
            <WorkflowRow key={useCase.use_case_id} useCase={useCase} />
          ))}
        </ul>
      ) : null}
      <Link to="/workflows" className={styles['see']}>
        See all
      </Link>
    </aside>
  )
}

function WorkflowRow({ useCase }: { useCase: Board['tiles'][number]['useCase'] }) {
  const { label, tone } = statusPill(useCase)
  return (
    <li data-workflow-id={useCase.use_case_id}>
      <OpenLink item={{ kind: 'workflow', id: useCase.use_case_id }} to={workflowPath(useCase)} state={FROM_LIST} className={styles['row']}>
        <StateMark tone={tone} label={label} />
        <b className={styles['name']}>{useCase.name}</b>
      </OpenLink>
    </li>
  )
}

/** The slim list for Home's chat: the person's workflows, read as the board reads them. It reads no run. */
export function ChatSlimList({ home, now }: { home: HomeOut; now: Date }) {
  const operator = isOperator(useMe().data)
  const useCases = useUseCases({ poll: REFRESH_MS })
  const board = boardOf(useCases.data ?? [], now)
  const problem =
    useCases.isError && !useCases.data ? (
      <div role="alert" className={styles['problem']}>
        <p>The workflows could not be loaded.</p>
        <Button onClick={() => void useCases.refetch()}>Try again</Button>
      </div>
    ) : null
  return <SlimList board={board} needs={needsTotal(home)} operator={operator} problem={problem} />
}
