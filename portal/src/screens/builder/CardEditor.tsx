import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { useCheckCard, useSaveCard, useTools } from '../../api/queries'
import type { CardProblem, CardView } from '../../api/types'
import { Button } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import { IconCheck } from '../../ui/icons'
import {
  approvalWords,
  EMPTY_BLOCK,
  EMPTY_INPUT,
  firstProblemKey,
  KIND_WORDS,
  removeAt,
  replaceAt,
  sortProblems,
  toDefinition,
  type CardDraft,
} from './cardDraft'
import { describedBy, Field } from './Field'
import { useDebounced } from './useDebounced'
import styles from './Form.module.css'
import editorStyles from './CardEditor.module.css'

const CHECK_DELAY_MS = 400
const CHANGED_MORE = 'Fix the points above first.'

interface CardEditorProps {
  initial: CardDraft
  /** The card to write a next version of. Null for a new card. */
  cardId: string | null
  onSaved: (card: CardView) => void
}

function problemsOf(error: unknown): CardProblem[] | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null
  const problems = (error.body as { problems?: unknown } | null)?.problems
  return Array.isArray(problems) ? (problems as CardProblem[]) : null
}

/** Write or change an agent card. The platform checks it as the Operator types and says which approvals it needs. */
export function CardEditor({ initial, cardId, onSaved }: CardEditorProps) {
  const explain = useErrorWords()
  const id = useId()
  const tools = useTools().data
  const save = useSaveCard()
  const [draft, setDraft] = useState(initial)
  const [refused, setRefused] = useState<CardProblem[] | null>(null)
  const [blocked, setBlocked] = useState(false)
  const settled = useDebounced(draft, CHECK_DELAY_MS)
  const definition = useMemo(() => toDefinition(settled), [settled])
  const checked = useCheckCard(definition)
  const checking = settled !== draft || checked.isFetching
  const focus = useRef<string | null>(null)

  const problems = refused ?? checked.data?.problems ?? []
  const sorted = sortProblems(problems)
  const approvals = approvalWords(checked.data?.approvals ?? [], tools)

  useEffect(() => {
    if (focus.current === null) return
    document.getElementById(focus.current)?.focus()
    focus.current = null
  })

  function change(next: CardDraft, focusId: string | null = null) {
    setDraft(next)
    setRefused(null)
    setBlocked(false)
    save.reset()
    focus.current = focusId
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!checking && problems.length > 0) {
      setBlocked(true)
      const key = firstProblemKey(sorted, draft.blocks.length, draft.inputs.length)
      focus.current = key === null ? `${id}-name` : key === 'name' || key === 'purpose' ? `${id}-${key}` : `${id}-${key.replace('.', '-')}-${key.startsWith('blocks') ? 'say' : 'name'}`
      document.getElementById(focus.current)?.focus()
      return
    }
    save.mutate(
      { cardId, card: toDefinition(draft) },
      {
        onSuccess: onSaved,
        onError: (error) => {
          const found = problemsOf(error)
          if (found) {
            setRefused(found)
            setBlocked(true)
          }
        },
      },
    )
  }

  const nameId = `${id}-name`
  const purposeId = `${id}-purpose`
  const first = (key: string) => sorted.byField[key]?.join(' ') ?? null

  return (
    <form className={editorStyles['form']} noValidate onSubmit={onSubmit}>
      <Field id={nameId} label="Name" problem={first('name')} quiet>
        <input
          id={nameId}
          value={draft.name}
          autoComplete="off"
          aria-invalid={first('name') ? true : undefined}
          aria-describedby={describedBy(nameId, false, first('name') !== null)}
          onChange={(event) => change({ ...draft, name: event.target.value })}
        />
      </Field>
      <Field id={purposeId} label="What it does" problem={first('purpose')} quiet>
        <textarea
          id={purposeId}
          value={draft.purpose}
          rows={2}
          aria-invalid={first('purpose') ? true : undefined}
          aria-describedby={describedBy(purposeId, false, first('purpose') !== null)}
          onChange={(event) => change({ ...draft, purpose: event.target.value })}
        />
      </Field>

      <fieldset className={editorStyles['group']}>
        <legend className={styles['legend']}>Steps</legend>
        {draft.blocks.map((block, at) => {
          const sayId = `${id}-blocks-${at}-say`
          const toolId = `${id}-blocks-${at}-tool`
          const problem = first(`blocks.${at}`)
          return (
            <div key={at} className={editorStyles['row']}>
              <Field id={sayId} label={`Step ${at + 1}`} problem={problem} quiet>
                <textarea
                  id={sayId}
                  value={block.say}
                  rows={2}
                  aria-invalid={problem ? true : undefined}
                  aria-describedby={describedBy(sayId, false, problem !== null)}
                  onChange={(event) => change({ ...draft, blocks: replaceAt(draft.blocks, at, { say: event.target.value }) })}
                />
              </Field>
              <div className={editorStyles['side']}>
                <Field
                  id={toolId}
                  label={
                    <>
                      Tool<span className="visually-hidden"> for step {at + 1}</span>
                    </>
                  }
                >
                  <select
                    id={toolId}
                    value={block.tool}
                    onChange={(event) => change({ ...draft, blocks: replaceAt(draft.blocks, at, { tool: event.target.value }) })}
                  >
                    <option value="">No tool</option>
                    {tools?.map((tool) => (
                      <option key={tool.id} value={tool.id}>
                        {tool.name}
                      </option>
                    ))}
                    {block.tool !== '' && !tools?.some((tool) => tool.id === block.tool) ? (
                      <option value={block.tool}>{block.tool}</option>
                    ) : null}
                  </select>
                </Field>
                <Button onClick={() => change({ ...draft, blocks: removeAt(draft.blocks, at) }, `${id}-add-step`)}>
                  Remove<span className="visually-hidden"> step {at + 1}</span>
                </Button>
              </div>
            </div>
          )
        })}
        <div>
          <Button
            id={`${id}-add-step`}
            onClick={() => change({ ...draft, blocks: [...draft.blocks, EMPTY_BLOCK] }, `${id}-blocks-${draft.blocks.length}-say`)}
          >
            Add step
          </Button>
        </div>
      </fieldset>

      <fieldset className={editorStyles['group']}>
        <legend className={styles['legend']}>Details to fill in for each run</legend>
        {draft.inputs.map((input, at) => {
          const nameFieldId = `${id}-inputs-${at}-name`
          const kindId = `${id}-inputs-${at}-kind`
          const exampleId = `${id}-inputs-${at}-example`
          const problem = first(`inputs.${at}`)
          return (
            <div key={at} className={editorStyles['row']}>
              <Field id={nameFieldId} label={`Detail ${at + 1}`} problem={problem} quiet>
                <input
                  id={nameFieldId}
                  value={input.name}
                  autoComplete="off"
                  aria-invalid={problem ? true : undefined}
                  aria-describedby={describedBy(nameFieldId, false, problem !== null)}
                  onChange={(event) => change({ ...draft, inputs: replaceAt(draft.inputs, at, { name: event.target.value }) })}
                />
              </Field>
              <div className={editorStyles['side']}>
                <Field
                  id={kindId}
                  label={
                    <>
                      Kind<span className="visually-hidden"> of detail {at + 1}</span>
                    </>
                  }
                >
                  <select
                    id={kindId}
                    value={input.kind}
                    onChange={(event) => change({ ...draft, inputs: replaceAt(draft.inputs, at, { kind: event.target.value }) })}
                  >
                    {Object.entries(KIND_WORDS).map(([kind, words]) => (
                      <option key={kind} value={kind}>
                        {words}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  id={exampleId}
                  label={
                    <>
                      Example<span className="visually-hidden"> for detail {at + 1}</span>
                    </>
                  }
                >
                  <input
                    id={exampleId}
                    value={input.example}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => change({ ...draft, inputs: replaceAt(draft.inputs, at, { example: event.target.value }) })}
                  />
                </Field>
                <Button onClick={() => change({ ...draft, inputs: removeAt(draft.inputs, at) }, `${id}-add-input`)}>
                  Remove<span className="visually-hidden"> detail {at + 1}</span>
                </Button>
              </div>
            </div>
          )
        })}
        <div>
          <Button
            id={`${id}-add-input`}
            onClick={() => change({ ...draft, inputs: [...draft.inputs, EMPTY_INPUT] }, `${id}-inputs-${draft.inputs.length}-name`)}
          >
            Add detail
          </Button>
        </div>
      </fieldset>

      <section className={editorStyles['approvals']} aria-labelledby={`${id}-approvals`}>
        <h3 id={`${id}-approvals`}>Approvals</h3>
        {approvals.length > 0 ? (
          <ul>
            {approvals.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">{checked.data ? 'None needed. This agent only reads.' : 'Checking.'}</p>
        )}
      </section>

      {sorted.general.length > 0 ? (
        <ul className={editorStyles['general']} aria-label="Points to fix">
          {sorted.general.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}

      <div className={styles['buttons']}>
        <Button type="submit" variant="primary" loading={save.isPending}>
          Save agent
        </Button>
        {!checking && problems.length === 0 && checked.data ? (
          <p className={editorStyles['ready']}>
            <IconCheck size={18} />
            Ready to save.
          </p>
        ) : null}
      </div>
      {blocked ? <InlineMessage tone="error">{CHANGED_MORE}</InlineMessage> : null}
      {save.isError && problemsOf(save.error) === null ? <InlineMessage tone="error">{explain(save.error)}</InlineMessage> : null}
    </form>
  )
}
