import { useParams } from 'react-router'
import { errorWords } from '../../api/errors'
import { useRun } from '../../api/queries'
import { useLiveRun, useTechnicalDetails } from '../../tracker/hooks'
import { Tracker } from '../../tracker/Tracker'
import { useRunTemplate } from '../../tracker/useRunTemplate'
import { ButtonLink } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { PageHeader } from '../../ui/PageHeader'
import { Minutes } from './Minutes'
import styles from './RunPage.module.css'

export function RunPage() {
  const { runId = '' } = useParams()
  const run = useRun(runId)
  const view = useLiveRun(runId, 'rest')
  const template = useRunTemplate(run.data)
  const [technical, setTechnical] = useTechnicalDetails()
  const closed = view.connection.is === 'closed' ? view.connection : null

  if (closed) {
    return (
      <div className="page">
        <PageHeader title={closed.reason === 'signed_out' ? 'Sign in first' : 'This run is not here'}>
          {closed.reason === 'signed_out' ? 'Sign in as one of the demo users, then open the run again.' : 'This run does not exist, or you cannot see it.'}
        </PageHeader>
        <ButtonLink to="/">Back to the runs</ButtonLink>
      </div>
    )
  }

  return (
    <div className={`page ${styles['page']}`}>
      <Tracker runId={runId} view={view} template={template} title={run.data?.use_case_name ?? 'Run'} />
      {run.isError ? <InlineMessage tone="error">{errorWords(run.error)}</InlineMessage> : null}
      <div className={styles['minutes']}>
        <Minutes entries={view.minutes} technical={technical} onTechnical={setTechnical} />
      </div>
    </div>
  )
}
