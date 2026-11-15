import { useId, useState } from 'react'
import { useNavigate } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useMadeInN8n, useSetUpFromN8n, type MadeInN8nView } from '../../api/madeInN8nQueries'
import { useDisplayName } from '../../api/people'
import type { Me } from '../../api/types'
import { Button } from '../../ui/Button'
import { madeInN8nWords } from './n8nMade'
import local from './MadeInN8n.module.css'
import styles from './Workflows.module.css'

interface RowProps {
  readonly workflow: MadeInN8nView
  readonly makerName: string
  readonly busy: boolean
  readonly onSetUp: () => void
}

function MadeRow({ workflow, makerName, busy, onSetUp }: RowProps) {
  const ids = useId()
  const words = madeInN8nWords(workflow, makerName)
  return (
    <li className={styles['row']} data-made-in-n8n={workflow.workflow_id}>
      <div className={local['row']}>
        <span className={styles['main']}>
          <span id={`${ids}-name`}>
            <b>{workflow.name}</b> {words.line}
          </span>
          <span id={`${ids}-sub`} className={styles['sub']}>
            {words.sub}
          </span>
        </span>
        <span className={local['end']}>
          <span className={styles['pill']} data-tone={words.pill.tone}>
            {words.pill.label}
          </span>
          {workflow.can_set_up ? (
            <Button loading={busy} onClick={onSetUp} aria-describedby={`${ids}-name ${ids}-sub`}>
              Set up
            </Button>
          ) : null}
        </span>
      </div>
    </li>
  )
}

/**
 * Workflows someone made in n8n that the platform does not run yet, for people with n8n access. Set up registers one and opens its page.
 * Nothing shows while none waits, or while n8n can't be opened from here.
 */
export function MadeInN8nSection({ me }: { me: Me }) {
  const access = me.n8n_access === true
  const waiting = useMadeInN8n(access)
  const setUp = useSetUpFromN8n()
  const navigate = useNavigate()
  const nameOf = useDisplayName()
  const errorWords = useErrorWords()
  const [problem, setProblem] = useState<string | null>(null)
  const headingId = useId()
  const workflows = waiting.data ?? []
  if (!access || workflows.length === 0) return null

  function press(workflowId: string) {
    if (setUp.isPending) return
    setProblem(null)
    setUp.mutate(workflowId, {
      onSuccess: (created) => void navigate(`/workflows/${created.use_case_id}`),
      onError: (error) => setProblem(errorWords(error)),
    })
  }

  return (
    <section className={styles['block']} aria-labelledby={headingId} data-section="made-in-n8n">
      <h2 id={headingId}>Made in n8n</h2>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      <ul className={styles['list']} aria-labelledby={headingId}>
        {workflows.map((workflow) => (
          <MadeRow
            key={workflow.workflow_id}
            workflow={workflow}
            makerName={nameOf(workflow.made_by)}
            busy={setUp.isPending && setUp.variables === workflow.workflow_id}
            onSetUp={() => press(workflow.workflow_id)}
          />
        ))}
      </ul>
    </section>
  )
}
