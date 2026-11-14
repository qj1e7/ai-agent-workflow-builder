import { useState } from 'react'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { useStartRun } from '../../api/queries'
import { useTurnOn } from '../../api/workflowQueries'
import type { UseCaseView } from '../../api/types'
import { Button } from '../../ui/Button'
import { useChatNavigate } from '../../ui/fromChat'
import { stageWords } from '../run/words'
import { controlsOf, stageOfLast, type Viewer } from './workflow'
import styles from './Workflows.module.css'

const DRAFT_WORDS = 'A draft. It runs only as a test, which writes nothing, until you turn it on after a test run passes.'

/**
 * A draft's own controls on its page and in the panel, as the set-up card has them (ADR 0044): Test run, which opens the run, and Turn it
 * on once a test run passed. The workflow reads On only once the platform answers that it is on.
 */
export function DraftActions({ useCase, viewer }: { useCase: UseCaseView; viewer: Viewer }) {
  const start = useStartRun()
  const turnOn = useTurnOn()
  const latch = useLatch()
  const navigate = useChatNavigate()
  const words = useErrorWords()
  const [problem, setProblem] = useState<string | null>(null)
  const controls = controlsOf(useCase, viewer)
  if (!controls.includes('test')) return null
  const passed = controls.includes('turn_on')
  const last = useCase.last_run

  const test = () =>
    latch.run((settled) =>
      start.mutate(
        { useCaseId: useCase.use_case_id, idempotencyKey: newIdempotencyKey(), test: true },
        { onSuccess: (run) => navigate(`/runs/${run.run_id}`), onError: (error) => setProblem(`Could not start the test run. ${words(error)}`), onSettled: settled },
      ),
    )
  const on = () => latch.run((settled) => turnOn.mutate(useCase.use_case_id, { onError: (error) => setProblem(`Could not turn it on. ${words(error)}`), onSettled: settled }))

  return (
    <div className={styles['draft']}>
      <p className="muted">{passed && last ? stageWords(stageOfLast(last), (id) => id) : DRAFT_WORDS}</p>
      <div className={styles['draftButtons']}>
        <Button variant={passed ? 'secondary' : 'primary'} loading={start.isPending} onClick={test}>
          Test run
        </Button>
        {passed ? (
          <Button variant="primary" loading={turnOn.isPending} onClick={on}>
            Turn it on
          </Button>
        ) : null}
      </div>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  )
}
