import { useRef } from 'react'
import { useParams } from 'react-router'
import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useRun } from '../../api/queries'
import type { RunState } from '../../api/types'
import { Caption } from '../../room/Caption'
import { useLiveRoom, useTechnicalDetails, useWidth } from '../../room/hooks'
import { Legend } from '../../room/Legend'
import { Minutes } from '../../room/Minutes'
import { ActionCard, TroubleshooterPanel } from '../../room/NeedsYou'
import { SpeechCard } from '../../room/pieces'
import { Room } from '../../room/Room'
import { expectedWritesOf, spineBlocks } from '../../room/spineBlocks'
import { Transport } from '../../room/Transport'
import { useBlocks } from '../../room/useBlocks'
import { ROOM_METRICS } from '../../run'
import { agentIdentity } from '../../ui/agents'
import { ButtonLink } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { PageHeader } from '../../ui/PageHeader'
import { Spine } from '../../ui/Spine'
import { StatusPill } from '../../ui/StatusPill'
import styles from './RunPage.module.css'

export function RunPage() {
  const { runId = '' } = useParams()
  const run = useRun(runId)
  const view = useLiveRoom(runId, 'rest')
  const blocks = useBlocks(run.data)
  const nameOf = useDisplayName()
  const [technical, setTechnical] = useTechnicalDetails()
  const roomRef = useRef<HTMLDivElement>(null)
  const width = useWidth(roomRef)
  const compact = width > 0 && width < ROOM_METRICS.wide.minWidth
  const { room } = view
  // The pill follows the room's own phase, the same source as the caption and the spine. The REST view
  // only speaks before the first frame has folded.
  const state: RunState | undefined = room.phase.name === 'empty' ? run.data?.state : room.phase.name
  const title = run.data?.use_case_name ?? 'Run'
  const startedBy = run.data ? nameOf(run.data.started_by) : null
  const needsYou = room.phase.name === 'failed' ? <TroubleshooterPanel runId={runId} view={view} /> : room.phase.name === 'awaiting_approval' ? <ActionCard view={view} /> : null
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
      <header className={styles['head']}>
        <h1 className={styles['title']}>{title}</h1>
        <p className={styles['lede']}>{run.data && startedBy ? `Started by ${startedBy} on ${formatDayAndTime(run.data.started_at)}.` : 'Loading the run.'}</p>
        {state ? (
          <div className={styles['pill']}>
            <StatusPill state={state} />
          </div>
        ) : null}
      </header>
      {run.isError ? <InlineMessage tone="error">{errorWords(run.error)}</InlineMessage> : null}
      <div className={styles['spine']}>
        {blocks ? <Spine blocks={spineBlocks(view, blocks)} orientation={compact ? 'vertical' : 'horizontal'} compact /> : null}
      </div>
      <div className={styles['columns']}>
        <div className={styles['stageColumn']}>
          <div ref={roomRef}>
            <Room view={view} width={width} expectedWrites={expectedWritesOf(blocks)} label={`The room for ${title}`} />
          </div>
          {compact && room.speech ? (
            <div className={styles['speechSlot']}>
              <SpeechCard speech={room.speech} speakerName={agentIdentity(room.speech.speaker).name} variant="slot" />
            </div>
          ) : null}
          <Caption room={room} />
          <Transport view={view} />
          <Legend />
        </div>
        <aside className={styles['rail']} aria-label="What needs you and the minutes">
          {needsYou}
          <div className={styles['minutes']}>
            <Minutes entries={view.minutes} technical={technical} onTechnical={setTechnical} />
          </div>
        </aside>
      </div>
    </div>
  )
}
