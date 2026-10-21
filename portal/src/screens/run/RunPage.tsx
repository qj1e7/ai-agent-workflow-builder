import { useParams } from 'react-router'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useRun } from '../../api/queries'
import { Caption } from '../../room/Caption'
import { useLiveRoom, useTechnicalDetails } from '../../room/hooks'
import { Minutes } from '../../room/Minutes'
import { ActionCard, TroubleshooterPanel } from '../../room/NeedsYou'
import { spineBlocks } from '../../room/spineBlocks'
import { useBlocks } from '../../room/useBlocks'
import { ButtonLink } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { PageHeader } from '../../ui/PageHeader'
import { Spine } from '../../ui/Spine'
import styles from './RunPage.module.css'

export function RunPage() {
  const { runId = '' } = useParams()
  const run = useRun(runId)
  const view = useLiveRoom(runId, 'rest')
  const blocks = useBlocks(run.data)
  const nameOf = useDisplayName()
  const [technical, setTechnical] = useTechnicalDetails()
  const { room } = view
  const title = run.data?.use_case_name ?? 'Run'
  const startedBy = run.data ? nameOf(run.data.started_by) : null
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
      <PageHeader title={title}>{run.data && startedBy ? `Started by ${startedBy} on ${formatDayAndTime(run.data.started_at)}.` : 'Loading the run.'}</PageHeader>
      {run.isError ? <InlineMessage tone="error">{errorWords(run.error)}</InlineMessage> : null}
      <div className={styles['columns']}>
        <div className={styles['stageColumn']}>
          {blocks ? <Spine blocks={spineBlocks(view, blocks)} orientation="vertical" compact /> : null}
          <Caption room={room} />
        </div>
        <aside className={styles['rail']} aria-label="What needs you and the minutes">
          {room.phase.name === 'awaiting_approval' ? <ActionCard view={view} /> : null}
          {room.phase.name === 'failed' ? <TroubleshooterPanel runId={runId} view={view} /> : null}
          <div className={styles['minutes']}>
            <Minutes entries={view.minutes} technical={technical} onTechnical={setTechnical} />
          </div>
        </aside>
      </div>
    </div>
  )
}
