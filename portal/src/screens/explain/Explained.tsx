import type { ReactNode } from 'react'
import type { WorkflowExplained } from '../../api/types'
import { Button } from '../../ui/Button'
import type { ExplainState } from './explain'
import styles from './Report.module.css'

interface ExplainedProps {
  readonly state: ExplainState
  readonly retry: () => void
  readonly children: (report: WorkflowExplained) => ReactNode
}

/** A report where it came, the server's own words where there is nothing to explain, and a reason with Try again when the load failed. Never a button that can't work. */
export function Explained({ state, retry, children }: ExplainedProps) {
  switch (state.kind) {
    case 'report':
      return children(state.report)
    case 'said':
      return <p role="status">{state.words}</p>
    case 'failed':
      return (
        <p className={styles['problem']} role="alert">
          The report could not be loaded. <Button onClick={retry}>Try again</Button>
        </p>
      )
    case 'loading':
      return (
        <p className="muted" role="status">
          Reading the workflow
        </p>
      )
  }
}
