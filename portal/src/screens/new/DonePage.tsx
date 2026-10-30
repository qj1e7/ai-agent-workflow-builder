import { useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useStartRun, useUseCase } from '../../api/queries'
import type { UseCaseView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { runWhen } from '../workflows/workflow'
import styles from './NewWorkflow.module.css'

function When({ useCase, now }: { useCase: UseCaseView; now: Date }) {
  if (useCase.state === 'paused') return <>is paused</>
  if (!useCase.next_run_at) return <>runs when an Operator starts it</>
  const at = runWhen(useCase.next_run_at, now)
  return (
    <>
      runs next <b>{at.startsWith('Today, ') ? `today at ${at.slice('Today, '.length)}` : `on ${at}`}</b>, Singapore time
    </>
  )
}

function Done({ useCase, now, draftKept }: { useCase: UseCaseView; now: Date; draftKept: boolean }) {
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useNavigate()
  const words = useErrorWords()
  const [key] = useState(newIdempotencyKey)
  const [problem, setProblem] = useState<string | null>(null)
  const testRun = () =>
    latch.run((settled) =>
      start.mutate(
        { useCaseId: useCase.use_case_id, idempotencyKey: key },
        {
          onSuccess: (started) => void navigate(`/runs/${started.run_id}`),
          onError: (error) => setProblem(words(error)),
          onSettled: settled,
        },
      ),
    )
  return (
    <div className={styles['done']}>
      <span className={styles['tick']}>
        <IconCheck size={44} strokeWidth={3} />
      </span>
      <h1 tabIndex={-1}>Your workflow is on</h1>
      <p>
        <b>{useCase.name}</b> <When useCase={useCase} now={now} />. When it needs a yes, an Approver gets a message in Teams.
      </p>
      {draftKept ? <p>Your draft is still on Home. This workflow is already on, so there is no need to turn it on again.</p> : null}
      <div className={styles['actions']}>
        <Button variant="primary" loading={start.isPending} onClick={testRun}>
          Do a test run now
        </Button>
        <ButtonLink to="/">Back to Home</ButtonLink>
      </div>
      {problem ? (
        <p className={styles['error']} role="alert">
          {problem}
        </p>
      ) : null}
      <p className={styles['note']}>A test run does the real work once, so it still waits for a yes before anything changes.</p>
    </div>
  )
}

export function DoneRoute({ now }: { now: Date }) {
  const { useCaseId = '' } = useParams()
  const draftKept = (useLocation().state as { draftKept?: unknown } | null)?.draftKept === true
  const useCase = useUseCase(useCaseId)
  if (useCase.data) return <Done useCase={useCase.data} now={now} draftKept={draftKept} />
  if (useCase.isError)
    return (
      <div className={styles['done']}>
        <h1 tabIndex={-1}>Workflow not found</h1>
        <p>It may have been deleted.</p>
        <ButtonLink to="/workflows">Go to Workflows</ButtonLink>
      </div>
    )
  return (
    <p className="muted" role="status">
      Loading
    </p>
  )
}
