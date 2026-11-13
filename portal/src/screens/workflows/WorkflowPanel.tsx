import { useState } from 'react'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { isOperator } from '../../api/me'
import { useDisplayName } from '../../api/people'
import { useMe, useModelOff, useTroubleshoot, useUseCase } from '../../api/queries'
import type { FailureReason, Me, UseCaseView } from '../../api/types'
import { useMoveWorkflow, useRereadWorkflow } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { IconPause, IconPlay } from '../../ui/icons'
import { useAfterPanelAction } from '../../ui/sidePanel'
import { Troubleshooting } from '../run/Outcome'
import { StatusBanner } from './Banner'
import { StatusPills } from './Status'
import { bannerOf, changeProblem, changeWords, controlsOf, lastRunWords, leftOutWords, NO_RUNS, nextRunWords, pillOf, pressChange, REFRESH_MS, rereadWhenOutOfDate, sentenceOf, viewerOf, type LastRun } from './workflow'
import styles from './Workflows.module.css'

/** A workflow in the side panel (spec 3.3): its status, its sentence, a stop's three answers with Retry, its last and next run, Open the run, and Pause or Resume. */
export function WorkflowPanel({ id, now }: { id: string; now: Date }) {
  const useCase = useUseCase(id, true, { poll: REFRESH_MS })
  const me = useMe()
  if (useCase.isError) {
    if (useCase.error instanceof ApiError && useCase.error.status === 404) return <p className="muted">That workflow isn’t here any more.</p>
    return (
      <p role="alert">
        The workflow could not be loaded. <Button onClick={() => void useCase.refetch()}>Try again</Button>
      </p>
    )
  }
  if (!useCase.data || !me.data) {
    return (
      <p className="muted" role="status">
        Loading the workflow
      </p>
    )
  }
  return <Summary useCase={useCase.data} me={me.data} now={now} />
}

/** The page's banner decides whether the workflow is stopped, so a paused one offers Resume here, never Retry, as on its page and row. */
function stopOf(useCase: UseCaseView, me: Me, now: Date): (LastRun & { readonly reason: FailureReason }) | null {
  const last = useCase.last_run
  if (bannerOf({ useCase, viewer: viewerOf(me), now }).tone !== 'bad' || last?.state !== 'failed' || last.reason === null) return null
  return { ...last, reason: last.reason }
}

function Summary({ useCase, me, now }: { useCase: UseCaseView; me: Me; now: Date }) {
  const nameOf = useDisplayName()
  const modelOff = useModelOff()
  const last = useCase.last_run
  const stopped = stopOf(useCase, me, now)
  const troubleshoot = useTroubleshoot(stopped?.run_id ?? '', stopped !== null, 0)
  const whole = bannerOf({ useCase, viewer: viewerOf(me), now })
  // A stop's Retry is in the answers below it, so its banner only opens the run. Resume is beside Pause. One primary action for the state.
  const banner = whole.action?.kind === 'stopped' ? { ...whole, action: { kind: 'open' as const, runId: whole.action.runId } } : whole.action?.kind === 'resume' ? { ...whole, action: null } : whole
  return (
    <>
      <div>
        <StatusPills state={useCase.state} fact={last ? pillOf(last) : null} test={last?.test === true} />
      </div>
      <p>{sentenceOf(useCase)}</p>
      {leftOutWords(useCase.left_out) ? <p className="muted">{leftOutWords(useCase.left_out)}</p> : null}
      <StatusBanner banner={banner} resuming={false} onResume={() => undefined} />
      {stopped ? (
        <Troubleshooting
          runId={stopped.run_id}
          failure={{ state: 'failed', stage: 'working', reason: stopped.reason, retryable: stopped.retryable, message: '' }}
          advice={troubleshoot.data}
          loading={troubleshoot.isPending}
          me={{ id: me.id, name: me.display, operator: isOperator(me) }}
          reports={[]}
          nameOf={nameOf}
          modelOff={modelOff}
        />
      ) : null}
      <dl className={styles['factrows']}>
        <div>
          <dt>Last run</dt>
          <dd>{lastRunWords(useCase, now, nameOf) ?? NO_RUNS}</dd>
        </div>
        <div>
          <dt>Next run</dt>
          <dd>{nextRunWords(useCase, now)}</dd>
        </div>
      </dl>
      <div className={styles['panelBtns']}>
        <PauseOrResume useCase={useCase} me={me} now={now} />
      </div>
    </>
  )
}

/** Only an Operator pauses or resumes, and the Software watchlist is paused on its own page. Nobody else sees a button. */
function PauseOrResume({ useCase, me, now }: { useCase: UseCaseView; me: Me; now: Date }) {
  const move = useMoveWorkflow()
  const reread = useRereadWorkflow()
  const changes = useLatch()
  const words = useErrorWords()
  const backToTop = useAfterPanelAction()
  const [said, setSaid] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const controls = controlsOf(useCase, viewerOf(me))
  const what = controls.includes('pause') ? 'pause' : controls.includes('resume') ? 'resume' : null
  if (what === null) return null

  const press = () =>
    pressChange(changes, (outcome) => move.mutate({ move: what, useCaseId: useCase.use_case_id }, outcome), {
      onSuccess: (view: UseCaseView) => {
        setProblem(null)
        setSaid(changeWords(what, view, now))
        backToTop?.()
      },
      onError: (error) => {
        rereadWhenOutOfDate(useCase.use_case_id, () => undefined, reread)(what)(error)
        setSaid(null)
        setProblem(changeProblem(what, useCase.name, error, words))
      },
    })

  return (
    <>
      <Button icon={what === 'pause' ? IconPause : IconPlay} loading={move.isPending} onClick={press}>
        {what === 'pause' ? 'Pause' : 'Resume'}
      </Button>
      <p className="visually-hidden" role="status">
        {said ?? ''}
      </p>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </>
  )
}
