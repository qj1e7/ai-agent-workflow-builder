import { useId, type ReactNode } from 'react'
import { useDisplayName } from '../../../api/people'
import type { PastDecisionView, UseCaseView, WatchedSoftwareView, WatchlistView } from '../../../api/types'
import { OpenLink } from '../../../ui/OpenItem'
import type { PanelItem } from '../../../ui/sidePanel'
import { SoftwareList } from '../../software/SoftwareList'
import { CHECKER, checksOnItsOwn, softwarePath } from '../../software/software'
import { StatusPills } from '../../workflows/Status'
import { isWatchlist, rowLine, workflowPath } from '../../workflows/workflow'
import type { NameOf } from '../../run/words'
import { decisionSub } from '../decided'
import styles from './Lists.module.css'
import { Pill } from '../../../ui/Pill'

/** The row is one button. Its name is the workflow or software, and its line and state are read after it as its description. */
function Row({ item, to, name, line, state, data }: { item: PanelItem; to: string; name: string; line: string; state: ReactNode; data: Record<string, string> }) {
  const id = useId()
  return (
    <li {...data}>
      <OpenLink item={item} to={to} className={styles['row']} aria-labelledby={`${id}n`} aria-describedby={`${id}l ${id}s`}>
        <span>
          <b id={`${id}n`}>{name}</b>
          <span id={`${id}l`} className={styles['sub']}>
            {line}
          </span>
        </span>
        <span id={`${id}s`}>{state}</span>
      </OpenLink>
    </li>
  )
}

/** Workflow rows in the words of the Workflows page's rows: the name, "Mon 9:00 · last run …", and the same pill. Each opens the workflow, beside the chat when the chat drew it. */
export function WorkflowRows({ useCases, label, now }: { useCases: readonly UseCaseView[]; label: string; now: Date }): ReactNode {
  const nameOf = useDisplayName()
  return (
    <ul className={styles['wl']} aria-label={label}>
      {useCases.map((useCase) => (
        <Row
          key={useCase.use_case_id}
          item={isWatchlist(useCase) ? { kind: 'watchlist' } : { kind: 'workflow', id: useCase.use_case_id }}
          to={workflowPath(useCase)}
          name={useCase.name}
          line={rowLine(useCase, now, nameOf)}
          state={<StatusPills useCase={useCase} test={useCase.last_run?.test === true} />}
          data={{ 'data-workflow-id': useCase.use_case_id }}
        />
      ))}
    </ul>
  )
}

/** Software rows drawn by the Watchlist page's own list, so the chat and the page say the same words in the same order. Each opens beside the chat. */
export function SoftwareRows({ rows, view, label }: { rows: readonly WatchedSoftwareView[]; view: Pick<WatchlistView, 'schedule' | 'state'>; label: string; now: Date }): ReactNode {
  return (
    <SoftwareList
      rows={rows}
      checkedBy={checksOnItsOwn(view) ? CHECKER : null}
      label={label}
      open={(row, className, cells) => (
        <OpenLink item={{ kind: 'software', id: row.id }} to={softwarePath(row.id)} className={className}>
          {cells}
        </OpenLink>
      )}
    />
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
            <Pill tone={decision.verdict === 'approve' ? 'good' : undefined}>{decision.verdict === 'approve' ? 'Approved' : 'Declined'}</Pill>
          }
          data={{ 'data-decision': decision.verdict }}
        />
      ))}
    </ul>
  )
}
