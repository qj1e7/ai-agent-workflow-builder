import { errorWords } from '../../api/errors'
import { useDisplayName } from '../../api/people'
import { useUseCases } from '../../api/queries'
import type { UseCaseView } from '../../api/types'
import { Button } from '../../ui/Button'
import { EmptyState, InlineMessage, Skeleton } from '../../ui/Feedback'
import { IconPlay, IconReplay } from '../../ui/icons'
import { formatDayAndTimeSeconds } from './useCaseTime'
import type { RunNow } from './useRunNow'
import styles from './UseCaseList.module.css'

export function UseCaseList({ runNow }: { runNow: RunNow }) {
  const useCases = useUseCases()

  return (
    <section className={styles['section']} aria-labelledby="use-cases-heading">
      <h2 id="use-cases-heading">Your use cases</h2>
      {useCases.data && useCases.data.length === 0 ? (
        <EmptyState title="No use cases yet.">
          Plan a task above and choose Save use case. It shows up here, ready to run.
        </EmptyState>
      ) : null}
      {useCases.data && useCases.data.length > 0 ? (
        <ul className={`panel ${styles['list']}`}>
          {useCases.data.map((useCase) => (
            <li key={useCase.use_case_id}>
              <UseCaseRow useCase={useCase} runNow={runNow} />
            </li>
          ))}
        </ul>
      ) : null}
      {!useCases.data && useCases.isError ? (
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load your use cases. {errorWords(useCases.error)}</InlineMessage>
          <Button icon={IconReplay} loading={useCases.isFetching} onClick={() => void useCases.refetch()}>
            Try again
          </Button>
        </div>
      ) : null}
      {!useCases.data && !useCases.isError ? (
        <div className={`panel ${styles['padded']}`}>
          <Skeleton lines={3} label="Loading your use cases" />
        </div>
      ) : null}
    </section>
  )
}

function UseCaseRow({ useCase, runNow }: { useCase: UseCaseView; runNow: RunNow }) {
  const nameOf = useDisplayName()
  const problem = runNow.errorFor(useCase.use_case_id)
  const starting = runNow.isStarting(useCase.use_case_id)

  return (
    <div className={styles['row']}>
      <div className={styles['what']}>
        <h3>{useCase.name}</h3>
        <p className={styles['instruction']}>{useCase.instruction}</p>
        <dl className={styles['meta']}>
          <div>
            <dt className="plan-voice">Owner</dt>
            <dd>{nameOf(useCase.owner)}</dd>
          </div>
          <div>
            <dt className="plan-voice">Version</dt>
            <dd>{useCase.version}</dd>
          </div>
          <div>
            <dt className="plan-voice">Created</dt>
            <dd>{formatDayAndTimeSeconds(useCase.created_at)}</dd>
          </div>
          <div>
            <dt className="plan-voice">ID</dt>
            <dd>{useCase.use_case_id}</dd>
          </div>
        </dl>
      </div>
      <div className={styles['run']}>
        <Button
          icon={IconPlay}
          loading={starting}
          disabled={runNow.anyStarting && !starting}
          onClick={() => runNow.start(useCase.use_case_id)}
        >
          Run now
        </Button>
        {problem ? <InlineMessage tone="error">{problem}</InlineMessage> : null}
      </div>
    </div>
  )
}
