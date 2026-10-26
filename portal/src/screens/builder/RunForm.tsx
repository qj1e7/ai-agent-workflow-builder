import { useId, useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import { useCreateAgentUseCase } from '../../api/queries'
import type { ToolView } from '../../api/types'
import { Button } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { IconPlay } from '../../ui/icons'
import {
  checkRun,
  defaultName,
  firstRunProblem,
  problemKey,
  refusedRun,
  startValues,
  type RunAgent,
  type RunProblems,
} from './agentRun'
import { describedBy, Field } from './Field'
import { ToolChips } from './ToolChips'
import { ModelNeeded } from './Trouble'
import { useRunNow } from './useRunNow'
import { tourStop } from '../../tour/stops'
import styles from './Form.module.css'
import runStyles from './RunForm.module.css'

interface RunFormProps {
  agents: readonly RunAgent[]
  /** The task the use case is saved with. */
  instruction: string
  tools: readonly ToolView[] | undefined
  /** Show each agent's name, purpose and tools. The library already shows them above the form. */
  showAgents?: boolean
}

const NO_PROBLEMS: RunProblems = { name: null, values: {}, form: null }

/** Save a use case from agents and start its first run. */
export function RunForm({ agents, instruction, tools, showAgents = true }: RunFormProps) {
  const explain = useErrorWords()
  const id = useId()
  const create = useCreateAgentUseCase()
  const runNow = useRunNow()
  const [name, setName] = useState(() => defaultName(agents))
  const [values, setValues] = useState(() => agents.map((agent) => startValues(agent)))
  const [problems, setProblems] = useState<RunProblems>(NO_PROBLEMS)
  const [created, setCreated] = useState<{ id: string; sent: string } | null>(null)
  const [refused, setRefused] = useState(false)

  const current = agents.map((agent, at) => ({ ...agent, values: values[at] ?? {} }))
  const starting = created ? runNow.isStarting(created.id) : false
  const busy = create.isPending || starting

  function focusFirst(found: RunProblems) {
    const key = firstRunProblem(found, current)
    if (key) document.getElementById(`${id}-${key === 'name' ? 'name' : key.replace(':', '-').replaceAll(' ', '_')}`)?.focus()
  }

  function change(edit: () => void) {
    edit()
    setProblems(NO_PROBLEMS)
    setRefused(false)
    create.reset()
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const checked = checkRun(name, instruction, current)
    if (!checked.ok) {
      setProblems(checked.problems)
      focusFirst(checked.problems)
      return
    }
    const sent = JSON.stringify(checked.body)
    // Created already and nothing changed: only the start failed, so start again without a second use case.
    if (created && created.sent === sent) {
      runNow.start(created.id)
      return
    }
    create.mutate(checked.body, {
      onSuccess: (made) => {
        setCreated({ id: made.use_case_id, sent })
        runNow.start(made.use_case_id)
      },
      onError: (error) => {
        const found = refusedRun(error, current)
        setRefused(found !== null)
        if (!found) return
        setProblems(found)
        focusFirst(found)
      },
    })
  }

  const nameId = `${id}-name`
  const startProblem = created ? runNow.errorFor(created.id) : null

  return (
    <form className={runStyles['form']} noValidate onSubmit={onSubmit} {...tourStop('run-details')}>
      {current.map((agent, at) => (
        <fieldset key={`${agent.card.card_id}-${at}`} className={runStyles['agent']}>
          <legend className={runStyles['legend']}>{agent.card.name}</legend>
          {showAgents ? (
            <>
              <p className="muted">{agent.card.purpose}</p>
              <ToolChips ids={agent.card.tools} tools={tools} />
            </>
          ) : null}
          {agent.card.inputs.map((input) => {
            const key = problemKey(at, input.name)
            const fieldId = `${id}-${at}-${input.name.replaceAll(' ', '_')}`
            const problem = problems.values[key] ?? null
            const value = agent.values[input.name] ?? ''
            const still = agent.missing.includes(input.name) && value.trim() === '' && !problem
            const help = still ? 'The Room lead could not find this in your task.' : input.what || null
            return (
              <Field key={input.name} id={fieldId} label={input.name} help={help} problem={problem}>
                <input
                  id={fieldId}
                  value={value}
                  placeholder={input.example}
                  disabled={busy}
                  autoComplete="off"
                  spellCheck={false}
                  aria-invalid={problem ? true : undefined}
                  aria-describedby={describedBy(fieldId, help !== null, problem !== null)}
                  onChange={(event) =>
                    change(() =>
                      setValues((all) => all.map((own, index) => (index === at ? { ...own, [input.name]: event.target.value } : own))),
                    )
                  }
                />
              </Field>
            )
          })}
        </fieldset>
      ))}
      <Field id={nameId} label="Name" problem={problems.name}>
        <input
          id={nameId}
          value={name}
          disabled={busy}
          autoComplete="off"
          aria-invalid={problems.name ? true : undefined}
          aria-describedby={describedBy(nameId, false, problems.name !== null)}
          onChange={(event) => change(() => setName(event.target.value))}
        />
      </Field>
      <div className={styles['buttons']}>
        <Button type="submit" variant="primary" icon={IconPlay} loading={busy} {...tourStop('save-and-run')}>
          Save and run
        </Button>
      </div>
      {problems.form ? <InlineMessage tone="error">{problems.form}</InlineMessage> : null}
      {create.isError && !refused ? <InlineMessage tone="error">{explain(create.error)}</InlineMessage> : null}
      {startProblem ? (
        created && runNow.needsModel(created.id) ? <ModelNeeded message={startProblem} /> : <InlineMessage tone="error">{startProblem}</InlineMessage>
      ) : null}
    </form>
  )
}
