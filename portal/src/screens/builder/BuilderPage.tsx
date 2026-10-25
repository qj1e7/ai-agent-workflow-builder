import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { usePlan, useMe } from '../../api/queries'
import { Button } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { IconFlow } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { EXAMPLE_TASK } from './plan'
import { AgentLibrary } from './AgentLibrary'
import { PlanPanel } from './PlanPanel'
import { Trouble } from './Trouble'
import { UseCaseList } from './UseCaseList'
import { useRunNow } from './useRunNow'
import { workOfPlan, type Work } from './work'
import styles from './BuilderPage.module.css'

export function BuilderPage() {
  const [task, setTask] = useState('')
  const [work, setWork] = useState<Work | null>(null)
  const operator = useMe().data?.roles.includes('operator') ?? false
  const [missing, setMissing] = useState(false)
  const planIt = usePlan()
  const heading = useRef<HTMLHeadingElement>(null)
  const moveToPanel = useRef(false)
  const runNow = useRunNow()
  const textarea = useRef<HTMLTextAreaElement>(null)
  const fieldId = useId()
  const helpId = `${fieldId}-help`
  const problemId = `${fieldId}-problem`

  useEffect(() => {
    if (!moveToPanel.current) return
    moveToPanel.current = false
    heading.current?.focus()
    heading.current?.scrollIntoView({ block: 'start' })
  }, [work])

  function ask(text: string) {
    planIt.mutate(text, { onSuccess: (answer) => setWork(workOfPlan(answer, text.trim())) })
  }

  function openWork(next: Work) {
    moveToPanel.current = true
    setWork(next)
  }

  function plan() {
    if (task.trim() === '') {
      setMissing(true)
      textarea.current?.focus()
      return
    }
    setMissing(false)
    ask(task)
  }

  function planFromKeyboard(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      plan()
    }
  }

  function planExample() {
    setTask(EXAMPLE_TASK)
    setMissing(false)
    ask(EXAMPLE_TASK)
  }

  const describedBy = [helpId, missing ? problemId : null].filter(Boolean).join(' ')

  return (
    <div className="page">
      <PageHeader title="Builder">Nothing is written to another system without an Approver.</PageHeader>

      <div className={styles['workspace']}>
        <section className={styles['ask']} aria-label="Describe the task">
          <label htmlFor={fieldId} className={styles['label']}>
            What should happen?
          </label>
          <textarea
            ref={textarea}
            id={fieldId}
            className={styles['task']}
            rows={6}
            value={task}
            aria-describedby={describedBy}
            aria-invalid={missing || undefined}
            onChange={(event) => {
              setTask(event.target.value)
              if (missing) setMissing(false)
            }}
            onKeyDown={planFromKeyboard}
          />
          <p id={helpId} className={styles['help']}>
            Name the system and when it should run.
          </p>
          {missing ? (
            <InlineMessage tone="error" id={problemId}>
              Write what should happen first.
            </InlineMessage>
          ) : null}
          <div className={styles['buttons']}>
            <Button variant="primary" icon={IconFlow} loading={planIt.isPending} onClick={plan}>
              Plan it
            </Button>
            <Button onClick={planExample}>Plan the example</Button>
          </div>
          {planIt.isError ? <Trouble error={planIt.error} /> : null}
        </section>

        <PlanPanel work={work} planning={planIt.isPending} onWork={openWork} heading={heading} />
      </div>

      <AgentLibrary operator={operator} onEdit={openWork} />

      <UseCaseList runNow={runNow} />
    </div>
  )
}
