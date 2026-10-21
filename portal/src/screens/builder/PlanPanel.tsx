import { useId, useState, type ChangeEvent, type ReactNode } from 'react'
import { errorWords } from '../../api/errors'
import { useCreateUseCase, useSuggest } from '../../api/queries'
import type { SuggestOut, TemplateView } from '../../api/types'
import { Button } from '../../ui/Button'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { IconPlay } from '../../ui/icons'
import { Spine } from '../../ui/Spine'
import {
  NO_MATCH_WORDS,
  createBody,
  draftProblems,
  editableParams,
  exampleParams,
  fieldWords,
  fixedParams,
  hasProblems,
  planBlocks,
} from './plan'
import type { RunNow } from './useRunNow'
import styles from './PlanPanel.module.css'

interface PlanPanelProps {
  suggest: ReturnType<typeof useSuggest>
  task: string
  runNow: RunNow
}

export function PlanPanel({ suggest, task, runNow }: PlanPanelProps) {
  return (
    <section className={`panel ${styles['panel']}`} aria-labelledby="plan-heading" aria-busy={suggest.isPending || undefined}>
      <h2 id="plan-heading">The Room lead's plan</h2>
      {suggest.isPending ? (
        <Skeleton lines={5} label="The Room lead is planning" />
      ) : suggest.data ? (
        <Outcome result={suggest.data} task={task} runNow={runNow} />
      ) : (
        <Waiting />
      )}
    </section>
  )
}

function Waiting() {
  return (
    <div className={styles['waiting']}>
      <div className={styles['ghost']} aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <p className="muted">The steps appear here.</p>
    </div>
  )
}

function Outcome({ result, task, runNow }: { result: SuggestOut; task: string; runNow: RunNow }) {
  if (!result.template) {
    return (
      <div className={styles['noMatch']}>
        <p>{NO_MATCH_WORDS}</p>
      </div>
    )
  }
  return (
    <>
      <div className={styles['template']}>
        <p className={styles['templateName']}>{result.template.name}</p>
        <p className="muted">{result.template.description}</p>
        <p className={styles['schedule']}>
          <IconPlay size={14} />
          Runs when you choose Run now. A weekly schedule is not built yet.
        </p>
      </div>
      <Spine blocks={planBlocks(result.template)} orientation="vertical" showDescriptions showState={false} label="Steps in this plan" />
      {result.matched_terms.length > 0 ? <MatchedTerms terms={result.matched_terms} /> : null}
      <PlanForm key={result.template.key} template={result.template} task={task} runNow={runNow} />
    </>
  )
}

function MatchedTerms({ terms }: { terms: readonly string[] }) {
  return (
    <div className={styles['matched']}>
      <h3 id="matched-heading">Matched your words</h3>
      <ul aria-labelledby="matched-heading" className={styles['chips']}>
        {terms.map((term) => (
          <li key={term}>{term}</li>
        ))}
      </ul>
    </div>
  )
}

interface Saved {
  useCaseId: string
  name: string
  version: number
}

function PlanForm({ template, task, runNow }: { template: TemplateView; task: string; runNow: RunNow }) {
  const [name, setName] = useState(template.name)
  const [params, setParams] = useState<Record<string, string>>(() => exampleParams(template))
  const [attempted, setAttempted] = useState(false)
  const [saved, setSaved] = useState<Saved | null>(null)
  const create = useCreateUseCase()
  const formId = useId()
  const problems = draftProblems(template, { name, params })

  function edit() {
    setSaved(null)
    create.reset()
  }

  function save() {
    setAttempted(true)
    if (hasProblems(problems)) {
      const firstId = problems.name ? `${formId}-name` : `${formId}-${Object.keys(problems.params)[0] ?? ''}`
      document.getElementById(firstId)?.focus()
      return
    }
    create.mutate(createBody(template, task, { name, params }), {
      onSuccess: (created) => setSaved({ useCaseId: created.use_case_id, name: name.trim(), version: created.version }),
    })
  }

  const onName = (event: ChangeEvent<HTMLInputElement>) => {
    setName(event.target.value)
    edit()
  }
  const onParam = (key: string) => (event: ChangeEvent<HTMLInputElement>) => {
    setParams((current) => ({ ...current, [key]: event.target.value }))
    edit()
  }

  const nameProblem = attempted ? problems.name : null

  return (
    <form
      className={styles['form']}
      noValidate
      onSubmit={(event) => {
        event.preventDefault()
        save()
      }}
    >
      <h3>Details</h3>
      <Field id={`${formId}-name`} label="Name" problem={nameProblem}>
        <input
          id={`${formId}-name`}
          value={name}
          onChange={onName}
          aria-invalid={nameProblem ? true : undefined}
          aria-describedby={nameProblem ? `${formId}-name-problem` : undefined}
          autoComplete="off"
        />
      </Field>
      {editableParams(template).map((param) => {
        const id = `${formId}-${param.name}`
        const problem = attempted ? (problems.params[param.name] ?? null) : null
        const { label, help } = fieldWords(param.description)
        const described = [help ? `${id}-help` : null, problem ? `${id}-problem` : null].filter((each) => each !== null).join(' ')
        return (
          <Field key={param.name} id={id} label={label} help={help} problem={problem}>
            <input
              id={id}
              value={params[param.name] ?? ''}
              onChange={onParam(param.name)}
              aria-invalid={problem ? true : undefined}
              aria-describedby={described || undefined}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        )
      })}
      <div className={styles['buttons']}>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Save use case
        </Button>
        {saved ? (
          <Button
            icon={IconPlay}
            loading={runNow.isStarting(saved.useCaseId)}
            disabled={runNow.anyStarting && !runNow.isStarting(saved.useCaseId)}
            onClick={() => runNow.start(saved.useCaseId)}
          >
            Run now
          </Button>
        ) : null}
      </div>
      {create.isError ? <InlineMessage tone="error">{errorWords(create.error)}</InlineMessage> : null}
      {saved ? (
        <InlineMessage tone="success">
          Saved {saved.name}, version {saved.version}.
        </InlineMessage>
      ) : null}
      {saved ? <RunError message={runNow.errorFor(saved.useCaseId)} /> : null}
      <details className={styles['details']}>
        <summary className="disclosure">Technical details</summary>
        <dl>
          <div>
            <dt>Plan</dt>
            <dd>{template.key}</dd>
          </div>
          {editableParams(template).map((param) => (
            <div key={param.name}>
              <dt>{param.description}</dt>
              <dd>{param.name}</dd>
            </div>
          ))}
          {fixedParams(template).map((param) => (
            <div key={param.name}>
              <dt>{param.description}, fixed by the plan</dt>
              <dd>
                <code>{param.example}</code>
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </form>
  )
}

function RunError({ message }: { message: string | null }) {
  return message ? <InlineMessage tone="error">{message}</InlineMessage> : null
}

interface FieldProps {
  id: string
  label: string
  help?: string | null
  problem: string | null
  children: ReactNode
}

function Field({ id, label, help = null, problem, children }: FieldProps) {
  return (
    <div className={styles['field']}>
      <label htmlFor={id}>{label}</label>
      {children}
      {help ? (
        <p id={`${id}-help`} className={styles['help']}>
          {help}
        </p>
      ) : null}
      {problem ? (
        <InlineMessage tone="error" id={`${id}-problem`}>
          {problem}
        </InlineMessage>
      ) : null}
    </div>
  )
}
