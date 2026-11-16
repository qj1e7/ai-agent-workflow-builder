import { Link, useParams, useSearchParams } from 'react-router'
import { useExplain } from '../../api/workflowQueries'
import { useFromChat } from '../../ui/fromChat'
import { IconChevronLeft } from '../../ui/icons'
import workflows from '../workflows/Workflows.module.css'
import { Explained } from './Explained'
import { explainStateOf, explainTitle } from './explain'
import { Report } from './Report'

/** `?version=3` names a version. Anything that isn't a whole number from 1 explains the version in use. */
export function versionOf(search: string | null): number | null {
  return search !== null && /^[1-9]\d{0,8}$/.test(search) ? Number(search) : null
}

/** More details of the side panel's Explain: one version's report on a page of its own, asked for without the reworded In short. */
export function ExplainRoute() {
  const { useCaseId = '' } = useParams()
  const version = versionOf(useSearchParams()[0].get('version'))
  const fromChat = useFromChat()
  const query = useExplain(useCaseId, { version })
  const state = explainStateOf(query)
  return (
    <>
      {fromChat ? null : (
        <Link to={`/workflows/${encodeURIComponent(useCaseId)}`} className={workflows['back']}>
          <IconChevronLeft size={16} />
          The workflow
        </Link>
      )}
      <div className={workflows['head']}>
        <div>
          <p className={workflows['kind']}>{explainTitle(version)}</p>
          <h1 tabIndex={-1}>{state.kind === 'report' ? state.report.name : 'Explain'}</h1>
        </div>
      </div>
      <Explained state={state} retry={() => void query.refetch()}>
        {(report) => <Report report={report} />}
      </Explained>
    </>
  )
}
