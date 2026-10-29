import { failureReasonLabel } from '../../api/labels'
import type { TroubleshootingOut } from '../../api/types'
import { ButtonLink } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import type { Phase, RunModel } from './runModel'
import { andList, plainWords, type NameOf } from './words'
import styles from './panels.module.css'

function BackHome() {
  return (
    <div className={styles['buttons']}>
      <ButtonLink to="/">Back to Home</ButtonLink>
    </div>
  )
}

/** Done or Declined: what the platform did after the decision, or that there was nothing to do. */
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
              {ref}
            </li>
          ))}
        </ul>
      ) : null}
      <BackHome />
    </div>
  )
}

type Failed = Extract<Phase, { state: 'failed' }>

/** The AI troubleshooter's reading of a failed run: what happened and what to do. */
export function Troubleshooting({ failure, advice, loading }: { failure: Failed; advice: TroubleshootingOut | undefined; loading: boolean }) {
  if (!advice) {
    return (
      <div className={styles['panel']}>
        <dl className={styles['qa']}>
          <dt>What happened</dt>
          <dd>{failureReasonLabel[failure.reason] ?? failure.reason}.</dd>
        </dl>
        <p className={styles['note']} role="status">
          {loading ? 'The AI troubleshooter is looking at what happened.' : 'The AI troubleshooter could not explain this one.'}
        </p>
      </div>
    )
  }
  const { explanation, likely_cause: cause, suggestion } = advice.advice
  return (
    <div className={styles['panel']}>
      <dl className={styles['qa']}>
        <dt>What happened</dt>
        <dd>{plainWords(`${explanation} ${cause}`)}</dd>
      </dl>
      <dl className={styles['qa']}>
        <dt>What to do</dt>
        <dd>{plainWords(suggestion)}</dd>
      </dl>
    </div>
  )
}
