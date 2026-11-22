import { useId, type ReactNode } from 'react'
import { useDisplayName } from '../../../api/people'
import { isOperator } from '../../../api/me'
import { useMe } from '../../../api/queries'
import type { PastDecisionView, UseCaseView, WatchedSoftwareView, WatchlistView } from '../../../api/types'
import { OpenLink } from '../../../ui/OpenItem'
import type { PanelItem } from '../../../ui/sidePanel'
import { CHECKER, checksOnItsOwn, softwareLine, softwarePath, stateOf, watchRank } from '../../software/software'
import { ExplainButton } from '../../explain/ExplainButton'
import { StatusPills } from '../../workflows/Status'
import { rowLine, SOFTWARE_PAGE, workflowPath } from '../../workflows/workflow'
import type { NameOf } from '../../run/words'
import { decisionSub } from '../decided'
import styles from './Lists.module.css'

/** The row is one button. Its name is the workflow or software, and its line and state are read after it as its description. */
function Row({ item, to, name, line, state, data, beside }: { item: PanelItem; to: string; name: string; line: string; state: ReactNode; data: Record<string, string>; beside?: ReactNode }) {
  const id = useId()
  return (
    <li {...data} className={beside === undefined ? undefined : styles['withBeside']}>
      <OpenLink item={item} to={to} className={styles['row']} aria-labelledby={`${id}n`} aria-describedby={`${id}l ${id}s`}>
        <span>
          <b id={`${id}n`}>{name}</b>
          <span id={`${id}l`} className={styles['sub']}>
            {line}
          </span>
        </span>
        <span id={`${id}s`}>{state}</span>
      </OpenLink>
      {beside}
    </li>
  )
}

/** Workflow rows in the words of the Workflows page's rows: the name, "Mon 9:00 · last run …", and the same pill. Each opens the workflow, beside the chat when the chat drew it. */
export function WorkflowRows({ useCases, label, now }: { useCases: readonly UseCaseView[]; label: string; now: Date }): ReactNode {
  const nameOf = useDisplayName()
  const me = useMe().data
  const operator = me !== undefined && isOperator(me)
  return (
    <ul className={styles['wl']} aria-label={label}>
      {useCases.map((useCase) => (
        <Row
          key={useCase.use_case_id}
          item={workflowPath(useCase) === SOFTWARE_PAGE ? { kind: 'watchlist' } : { kind: 'workflow', id: useCase.use_case_id }}
          to={workflowPath(useCase)}
          name={useCase.name}
          line={rowLine(useCase, now, nameOf)}
          state={<StatusPills useCase={useCase} operator={operator} test={useCase.last_run?.test === true} />}
          data={{ 'data-workflow-id': useCase.use_case_id }}
          beside={<ExplainButton useCaseId={useCase.use_case_id} name={useCase.name} />}
        />
      ))}
    </ul>
  )
}

/** Software rows in the words and order of the Watchlist page's rows: urgent first, the name, "1.2.14 → 1.2.16 · checked by …", and the same pill. */
export function SoftwareRows({ rows, view, label, now }: { rows: readonly WatchedSoftwareView[]; view: Pick<WatchlistView, 'schedule' | 'state'>; label: string; now: Date }): ReactNode {
  const checkedBy = checksOnItsOwn(view) ? CHECKER : null
  const sorted = [...rows].sort((a, b) => watchRank(a) - watchRank(b))
  return (
    <ul className={styles['wl']} aria-label={label}>
      {sorted.map((row) => {
        const state = stateOf(row)
        return (
          <Row
            key={row.id}
            item={{ kind: 'software', id: row.id }}
            to={softwarePath(row.id)}
            name={row.name}
            line={softwareLine(row, now, checkedBy)}
            state={
              <span className={styles['pill']} data-tone={state.tone}>
                {state.words}
              </span>
            }
            data={{ 'data-software-id': row.id }}
          />
        )
      })}
    </ul>
  )
}

/** Decision rows in the sketch's decisions card: the workflow, the day with the reason or what the yes led to, and Approved or Declined. Each opens the run. */
export function DecisionRows({ decisions, label, now, nameOf }: { decisions: readonly PastDecisionView[]; label: string; now: Date; nameOf: NameOf }): ReactNode {
  return (
    <ul className={styles['wl']} aria-label={label}>
      {decisions.map((decision) => (
        <Row
          key={`${decision.run_id}:${decision.at}`}
          item={{ kind: 'run', id: decision.run_id }}
          to={`/runs/${decision.run_id}`}
          name={decision.use_case_name}
          line={decisionSub(decision, now, nameOf)}
          state={
            <span className={styles['pill']} data-tone={decision.verdict === 'approve' ? 'good' : undefined}>
              {decision.verdict === 'approve' ? 'Approved' : 'Declined'}
            </span>
          }
          data={{ 'data-decision': decision.verdict }}
        />
      ))}
    </ul>
  )
}
