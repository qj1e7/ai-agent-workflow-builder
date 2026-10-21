import { useId, useRef, useState, type KeyboardEvent } from 'react'
import { errorWords } from '../../api/errors'
import { useSuggest } from '../../api/queries'
import { Button } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { IconFlow } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { EXAMPLE_TASK } from './plan'
import { PlanPanel } from './PlanPanel'
import { UseCaseList } from './UseCaseList'
import { useRunNow } from './useRunNow'
import styles from './BuilderPage.module.css'

export function BuilderPage() {
  const [task, setTask] = useState('')
  const [missing, setMissing] = useState(false)
  const suggest = useSuggest()
  const runNow = useRunNow()
  const textarea = useRef<HTMLTextAreaElement>(null)
  const fieldId = useId()
  const helpId = `${fieldId}-help`
  const problemId = `${fieldId}-problem`

  function plan() {
    if (task.trim() === '') {
      setMissing(true)
      textarea.current?.focus()
      return
    }
    setMissing(false)
    suggest.mutate(task)
  }

  function planFromKeyboard(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      plan()
    }
  }

  function useExample() {
    setTask(EXAMPLE_TASK)
    setMissing(false)
    textarea.current?.focus()
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
            <Button variant="primary" icon={IconFlow} loading={suggest.isPending} onClick={plan}>
              Plan it
            </Button>
            <Button onClick={useExample}>Use the example</Button>
          </div>
          {suggest.isError ? <InlineMessage tone="error">{errorWords(suggest.error)}</InlineMessage> : null}
        </section>

        <PlanPanel suggest={suggest} task={task} runNow={runNow} />
      </div>

      <UseCaseList runNow={runNow} />
    </div>
  )
}
