import { useExplain } from '../../api/workflowQueries'
import { Explained } from './Explained'
import { explainStateOf } from './explain'
import { Report } from './Report'
import styles from './Report.module.css'

/** One version's report in the side panel: the workflow's name, then the report. It asks without the reworded In short, which only the chat card asks for. */
export function ExplainPanel({ id, version }: { id: string; version: number | null }) {
  const query = useExplain(id, { version })
  return (
    <Explained state={explainStateOf(query)} retry={() => void query.refetch()}>
      {(report) => (
        <>
          <h3 className={styles['name']}>{report.name}</h3>
          <Report report={report} />
        </>
      )}
    </Explained>
  )
}
