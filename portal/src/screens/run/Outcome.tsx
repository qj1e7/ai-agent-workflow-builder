import { useId, type ReactNode } from 'react'
import { failureReasonLabel } from '../../api/labels'
import type { TroubleshootingOut } from '../../api/types'
import { ButtonLink } from '../../ui/Button'
import { RetryButton } from '../home/HomeItem'
import { stoppedActions } from '../home/home'
import { ReportToSupport } from './Report'
import type { Phase, RunModel } from './runModel'
import type { Answer } from './stageAnswers'
import { failureText } from './support'
import { withCurrentNames, type NameOf } from './words'
import styles from './panels.module.css'

function BackHome() {
  return (
    <div className={styles['buttons']}>
      <ButtonLink to="/">Back to Home</ButtonLink>
    </div>
  )
}

/**
 * What stays on a finished run's page past its settled line: what the run didn’t check and the questions, read only (spec 10.4),
 * and what happens next after a decline. The ticket and the decline reason are in the settled line, so they are not said again here.
 */
export function Outcome({ declinedNext = null, record = null }: { declinedNext?: string | null; record?: ReactNode }) {
  if (declinedNext === null && record === null) return <BackHome />
  return (
    <div className={styles['panel']}>
      {declinedNext ? <p>{declinedNext}</p> : null}
      {record}
      <BackHome />
    </div>
  )
}

type Failed = Extract<Phase, { state: 'failed' }>

export const OPERATORS_RETRY = 'An Operator can retry the run.'
export const OPERATORS_REPORT = 'An Operator can report this to support.'

/** Safe to retry while no AI model is connected: a retry would fail again, so the platform's Yes is not yet true (spec 5.4). */
export const NOT_YET_NO_MODEL = 'Not yet. A retry would stop in the same place until an AI model is connected.'

export interface TroubleshootingProps {
  readonly runId: string
  readonly failure: Failed
  readonly advice: TroubleshootingOut | undefined
  readonly loading: boolean
  readonly me: { readonly id: string; readonly name: string; readonly operator: boolean } | undefined
  readonly reports: RunModel['reports']
  readonly nameOf: NameOf
  /** No working AI model: a retry would fail again, so the run waits (spec 5.4). */
  readonly modelOff?: boolean
  /** The page already has its main button, so none here is primary. */
  readonly quiet?: boolean
}

function Qa({ name, id, children }: { name: string; id?: string; children: ReactNode }) {
  return (
    <div>
      <dt>{name}</dt>
      <dd id={id}>{children}</dd>
    </div>
  )
}

/** The troubleshooter's rows as the sketch's `dt`/`dd` list. */
export function AnswerList({ answers, children }: { answers: readonly Answer[]; children?: ReactNode }) {
  return (
    <dl className={styles['answers']}>
      {answers.map((answer) => (
        <Qa key={answer.label} name={answer.label}>
          {answer.text}
        </Qa>
      ))}
      {children}
    </dl>
  )
}

/**
 * The AI troubleshooter's three answers: What happened, Affected and Safe to retry. What happened is its one sentence; the likely
 * cause and the platform's failure text wait behind Details. Someone who isn't an Operator reads the answers, and a note where the buttons are.
 */
export function StopAnswers({ failure, advice, loading, modelOff = false, safeId }: Pick<TroubleshootingProps, 'failure' | 'advice' | 'loading' | 'modelOff'> & { safeId: string }) {
  const note = failureText(failure.message)
  const happened = advice ? withCurrentNames(advice.answers.what_happened) : `${failureReasonLabel[failure.reason] ?? failure.reason}.`
  const cause = advice ? withCurrentNames(advice.advice.likely_cause) : ''
  const waitsForModel = failure.retryable && modelOff
  const details = [cause, note ? `The failure text: ${note}` : ''].filter((part) => part !== '')
  return (
    <>
      <dl className={styles['answers']}>
        <Qa name="What happened">{happened}</Qa>
        {advice ? (
          <>
            <Qa name="Affected">{advice.answers.what_affected}</Qa>
            <Qa name="Safe to retry" id={safeId}>
              {waitsForModel ? NOT_YET_NO_MODEL : withCurrentNames(advice.answers.safe_to_retry)}
            </Qa>
          </>
        ) : null}
      </dl>
      {advice ? null : (
        <p className={styles['note']} role="status">
          {loading ? 'The AI troubleshooter is looking at what happened.' : 'The AI troubleshooter could not explain this one.'}
        </p>
      )}
      {details.length > 0 ? (
        <details className={styles['details']}>
          <summary>Details</summary>
          {details.map((part) => (
            <p key={part}>{part}</p>
          ))}
        </details>
      ) : null}
    </>
  )
}

/**
 * Under the answers, the one next step: Retry when the platform says the run can run again, or Report to support when it can't.
 * Both ask stoppedActions, the same rule Home uses. With no AI model a retry would fail again, so there is neither.
 */
export function StopNext({ runId, failure, advice, me, reports, nameOf, modelOff = false, quiet = false, safeId }: Omit<TroubleshootingProps, 'loading'> & { safeId: string }) {
  const [first] = stoppedActions(runId, failure.retryable, modelOff)
  const retry = first?.kind === 'retry'
  const waitsForModel = failure.retryable && modelOff
  const found = [advice ? withCurrentNames(advice.answers.what_happened) : `${failureReasonLabel[failure.reason] ?? failure.reason}.`, failureText(failure.message)].filter((part) => part !== '').join(' ')
  if (waitsForModel) return null
  if (retry) {
    return me?.operator ? <RetryButton runId={runId} label="Retry" primary={!quiet} describedBy={safeId} stay /> : <p className={styles['note']}>{OPERATORS_RETRY}</p>
  }
  return me?.operator || reports.length > 0 ? (
    <ReportToSupport runId={runId} found={found} me={me?.id} meName={me?.name ?? 'A teammate'} reports={reports} nameOf={nameOf} quiet={quiet} />
  ) : (
    <p className={styles['note']}>{OPERATORS_REPORT}</p>
  )
}

/** The answers with the next step under them, for the run page and the side panel. `bare` leaves out the box, for a place that draws its own. */
export function Troubleshooting(props: TroubleshootingProps & { readonly bare?: boolean }) {
  const safeId = useId()
  return (
    <div className={props.bare ? styles['bare'] : styles['panel']}>
      <StopAnswers {...props} safeId={safeId} />
      <div className={styles['buttons']}>
        <StopNext {...props} safeId={safeId} />
      </div>
    </div>
  )
}
