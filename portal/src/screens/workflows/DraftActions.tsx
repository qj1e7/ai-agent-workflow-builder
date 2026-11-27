import { useState, type ReactNode } from 'react'
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

interface Draft {
  /** The one sentence on where the draft stands: what it does until a test run passes, or how the last one went. */
  readonly words: string
  readonly buttons: ReactNode
  readonly problem: ReactNode
}

/**
 * A draft's own controls, as the set-up card has them (ADR 0044): Test run, which opens the run, and Turn it on once a test run passed.
 * The workflow reads On only once the platform answers that it is on. A page puts the buttons in its title row and the words under the
 * sentence, and the panel puts all three together in DraftActions. Null while the person has no test to press.
 */
export function useDraft(useCase: UseCaseView, viewer: Viewer): Draft | null {
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

  return {
    words: passed && last ? stageWords(stageOfLast(last), (id) => id) : DRAFT_WORDS,
    buttons: (
      <>
        <Button variant={passed ? 'secondary' : 'primary'} loading={start.isPending} onClick={test}>
          Test run
        </Button>
        {passed ? (
          <Button variant="primary" loading={turnOn.isPending} onClick={on}>
            Turn it on
          </Button>
        ) : null}
      </>
    ),
    problem: problem ? (
      <p className={styles['problem']} role="alert">
        {problem}
      </p>
    ) : null,
  }
}

/** A draft's words, buttons and problem in one block, as the side panel has them. */
export function DraftActions({ useCase, viewer }: { useCase: UseCaseView; viewer: Viewer }) {
  const draft = useDraft(useCase, viewer)
  if (!draft) return null
  return (
    <div className={styles['draft']}>
      <p className="muted">{draft.words}</p>
      <div className={styles['draftButtons']}>{draft.buttons}</div>
      {draft.problem}
    </div>
  )
}
