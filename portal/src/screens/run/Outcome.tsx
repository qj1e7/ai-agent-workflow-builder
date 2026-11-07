import { useId, type ReactNode } from 'react'
import { failureReasonLabel } from '../../api/labels'
import type { TroubleshootingOut } from '../../api/types'
import { ButtonLink } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { RetryButton } from '../home/HomeItem'
import { CAN_RUN_AGAIN, stoppedActions } from '../home/home'
import { TicketLink } from '../jira/TicketKeys'
import { ReportToSupport } from './Report'
import type { Phase, RunModel } from './runModel'
import { failureText, suggestionFor } from './support'
import { andList, withCurrentNames, type NameOf } from './words'
import styles from './panels.module.css'

function BackHome() {
  return (
    <div className={styles['buttons']}>
      <ButtonLink to="/">Back to Home</ButtonLink>
    </div>
  )
}

export function Outcome({ model, nameOf }: { model: RunModel; nameOf: NameOf }) {
  const { phase } = model
  if (phase.state === 'rejected') {
    return (
      <div className={styles['panel']}>
        <h2>Declined</h2>
        <p>{nameOf(phase.by)} declined, so nothing was written.</p>
        <BackHome />
      </div>
    )
  }
  const refs = model.written.map((written) => written.ref)
  const urls = new Map(model.written.map((written) => [written.ref, written.url ?? null]))
  const jiraRefs = new Set(model.written.filter((written) => written.connector === 'jira' && written.ref !== '').map((written) => written.ref))
  const tickets = model.written.length > 0 && model.written.every((written) => written.operation === 'create_ticket')
  const approvers = andList(model.approvedBy.map(nameOf)) || 'An Approver'
  let did = 'There was nothing to write.'
  if (refs.length > 0) did = `${approvers} approved, and the platform ${tickets ? `created the ${refs.length === 1 ? 'ticket' : 'tickets'}` : 'wrote the changes'}.`
  return (
    <div className={styles['panel']}>
      <h2>
        <span className={styles['okMark']}>
          <IconCheck size={18} />
        </span>
        Done
      </h2>
      <p>{did}</p>
      {refs.length > 0 ? (
        <ul className={styles['chips']} aria-label="Written">
          {refs.map((ref) => (
            <li key={ref} className={styles['chip']}>
              <IconCheck size={12} />
              {jiraRefs.has(ref) ? <TicketLink ticketKey={ref} href={urls.get(ref)} /> : ref}
            </li>
          ))}
        </ul>
      ) : null}
      <BackHome />
    </div>
  )
}

type Failed = Extract<Phase, { state: 'failed' }>

export const OPERATORS_RETRY = 'An Operator can retry this run.'

interface TroubleshootingProps {
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
    <dl className={styles['qa']}>
      <dt id={id}>{name}</dt>
      <dd>{children}</dd>
    </dl>
  )
}

/**
 * The AI troubleshooter's four answers. The last one is the action: Retry when the platform says the run can run again,
 * or Report to support when it can't. Both ask stoppedActions, the same rule Home uses.
 */
export function Troubleshooting({ runId, failure, advice, loading, me, reports, nameOf, modelOff = false, quiet = false }: TroubleshootingProps) {
  const doId = useId()
  const note = failureText(failure.message)
  const happened = advice
    ? withCurrentNames(`${advice.answers.what_happened} ${advice.advice.likely_cause}`)
    : `${failureReasonLabel[failure.reason] ?? failure.reason}.`
  const [first] = stoppedActions(runId, failure.retryable, modelOff)
  const retry = first?.kind === 'retry'
  const waitsForModel = failure.retryable && modelOff
  const suggestion = advice ? suggestionFor(advice.advice.suggestion) : ''
  const found = [happened, note].filter((part) => part !== '').join(' ')
  return (
    <div className={styles['panel']}>
      <Qa name="What happened">
        {happened}
        {note ? <span className={styles['failureText']}>The failure text: {note}</span> : null}
      </Qa>
      {advice ? (
        <>
          <Qa name="What was affected">{advice.answers.what_affected}</Qa>
          <Qa name="Can it be fixed safely">{advice.answers.can_fix}</Qa>
        </>
      ) : (
        <p className={styles['note']} role="status">
          {loading ? 'The AI troubleshooter is looking at what happened.' : 'The AI troubleshooter could not explain this one.'}
        </p>
      )}
      <Qa name="What should you do" id={doId}>
        {suggestion ? <span>{suggestion}</span> : null}
        {waitsForModel ? (
          <span className={styles['note']}>{CAN_RUN_AGAIN}</span>
        ) : retry ? (
          me?.operator ? (
            <span className={styles['buttons']}>
              <RetryButton runId={runId} label="Retry the run" primary={!quiet} describedBy={doId} />
            </span>
          ) : (
            <span className={styles['note']}>{OPERATORS_RETRY}</span>
          )
        ) : (
          <ReportToSupport runId={runId} found={found} me={me?.id} meName={me?.name ?? 'A teammate'} reports={reports} nameOf={nameOf} quiet={quiet} />
        )}
      </Qa>
    </div>
  )
}
