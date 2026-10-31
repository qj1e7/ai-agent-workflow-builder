import type { RowKind } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconCheck, IconPencil } from '../../ui/icons'
import { checkedRows, lowerFirst, NAME_LIMIT, textsOf, whenWords, type Form, type PlanView } from './draft'
import styles from './NewWorkflow.module.css'

const PROMISES = [
  'Nothing changes without a yes. A request never says yes by itself.',
  'You can pause, change or delete it at any time from its page in Workflows.',
  'If it stops, the AI troubleshooter tells you why on the Home page.',
] as const

const partsOf = (form: Form, kind: RowKind) => textsOf(form.rows, kind).join(' and ')

interface StepReviewProps {
  readonly form: Form
  readonly plan: PlanView
  /** The drafted agents the Operator already saved, which Turn it on reuses. */
  readonly reused: ReadonlySet<number>
  readonly nameProblem: string | null
  readonly busy: boolean
  readonly problems: readonly string[]
  readonly onName: (name: string) => void
  readonly onBack: () => void
  readonly onTurnOn: () => void
}

export function StepReview({ form, plan, reused, nameProblem, busy, problems, onName, onBack, onTurnOn }: StepReviewProps) {
  const agents = plan.kind === 'agents' ? plan.agents : []
  const drafted = agents.filter((agent) => agent.card.kind === 'drafted')
  const fresh = drafted.some((agent) => !reused.has(agent.index))
  const again = drafted.some((agent) => reused.has(agent.index))
  return (
    <>
      <div className={styles['body']}>
        <div className={styles['field']}>
          <label htmlFor="workflow-name">Name</label>
          <input
            id="workflow-name"
            type="text"
            maxLength={NAME_LIMIT + 20}
            value={form.name}
            aria-invalid={nameProblem ? true : undefined}
            aria-describedby={nameProblem ? 'workflow-name-error' : undefined}
            onChange={(event) => onName(event.target.value)}
          />
          {nameProblem ? (
            <span className={styles['error']} id="workflow-name-error">
              {nameProblem}
            </span>
          ) : null}
        </div>
        <p className={styles['sentence']}>
          <mark>{whenWords(form.when)}</mark> Singapore time, the agents find <mark>{lowerFirst(partsOf(form, 'look_for'))}</mark> and{' '}
          <mark>{lowerFirst(partsOf(form, 'do'))}</mark>. Before they change anything, an Approver says yes in Teams.
        </p>
        <dl className={styles['kv']}>
          <dt>Where it goes</dt>
          <dd>{partsOf(form, 'where')}</dd>
          <dt>Who says yes</dt>
          <dd>Any Approver except you, in Teams. Nobody approves their own work.</dd>
          <dt>Done by</dt>
          <dd>
            {agents.map((agent) => agent.name).join(' and ')}
            {fresh ? '. The new agent is saved to the Agent library.' : ''}
            {again ? '. This workflow uses the agent you already saved in the Agent library.' : ''}
          </dd>
        </dl>
        <section className={styles['panel']} aria-labelledby="checked-h">
          <h2 id="checked-h">Checked against your request</h2>
          <ul className={styles['checks']}>
            {checkedRows(form).map((row) => (
              <li key={row.words} data-changed={!row.ok || undefined}>
                {row.ok ? <IconCheck size={16} /> : <IconPencil size={16} />}
                <span>{row.words}</span>
              </li>
            ))}
          </ul>
        </section>
        <ul className={styles['checks']}>
          {PROMISES.map((promise) => (
            <li key={promise}>
              <IconCheck size={16} />
              <span>{promise}</span>
            </li>
          ))}
        </ul>
        {problems.length > 0 ? (
          <div role="alert" className={styles['error']}>
            {problems.map((problem) => (
              <p key={problem}>{problem}</p>
            ))}
          </div>
        ) : null}
      </div>
      <div className={styles['foot']}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="primary" loading={busy} onClick={onTurnOn}>
          Turn it on
        </Button>
      </div>
    </>
  )
}
