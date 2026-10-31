import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useTools } from '../../api/queries'
import type { ToolId, ToolView } from '../../api/types'
import { Button, ButtonLink, buttonClassName } from '../../ui/Button'
import { IconAlert, IconInfo, IconPencil } from '../../ui/icons'
import { systemOf } from '../agents/agents'
import { canDrop, nextBlockers, ROW_LABEL, valueKey, valueOf, valueProblem, type ChipState, type Form, type PlanAgent, type PlanView, type Redirect, type Row } from './draft'
import { PlannerSays } from './StepDescribe'
import styles from './NewWorkflow.module.css'

const HINT: Record<ChipState, string> = {
  understood: 'from your words',
  changed: 'from your words',
  edited: 'changed by you',
  missing: 'please fill in',
  cant_do: 'can’t do this yet',
  checking: 'checking your new words',
}

type ToolKinds = ReadonlyMap<ToolId, ToolView['kind']>

function tagOf(tool: ToolId | null, kinds: ToolKinds): { readonly words: string; readonly writes: boolean } {
  if (tool === null) return { words: 'No system access', writes: false }
  return kinds.get(tool) === 'read' ? { words: `Reads ${systemOf(tool)}`, writes: false } : { words: 'Changes data, waits for a yes', writes: true }
}

export const fixId = (index: number) => `row-${index}-fix`
export const valueId = (agent: number, input: string) => `value-${agent}-${input.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
const PROBLEMS_ID = 'plan-problems'

function NextButton({ blocked, describedBy, onNext, onBlocked }: { blocked: boolean; describedBy: string; onNext: () => void; onBlocked: () => void }) {
  return (
    <button type="button" className={buttonClassName('primary')} aria-disabled={blocked || undefined} aria-describedby={blocked ? describedBy : undefined} onClick={blocked ? onBlocked : onNext}>
      Next
    </button>
  )
}

export interface PlanState {
  readonly view: PlanView | null
  readonly pending: boolean
  readonly error: string | null
  readonly retry: () => void
  /** The drafted agents the Operator already saved, which Turn it on reuses. */
  readonly reused: ReadonlySet<number>
}

function WatchlistStep({ redirect, onBack, onCarryOn }: { redirect: Redirect; onBack: () => void; onCarryOn: () => void }) {
  return (
    <>
      <div className={styles['body']}>
        <PlannerSays>{redirect.note}</PlannerSays>
        <div className={styles['panel']}>
          <h2>Add it to the Software watchlist</h2>
          <p>
            One list means one check and one Teams approval a week, however much software you add.
            {redirect.software ? ` Add ${redirect.software} there, with the GitHub project it is published on.` : ''}
          </p>
          <div className={styles['actions']}>
            <ButtonLink variant="primary" to="/software">
              Open Software watchlist
            </ButtonLink>
          </div>
        </div>
      </div>
      <div className={styles['foot']}>
        <Button onClick={onBack}>Back</Button>
        <Button onClick={onCarryOn}>No, set it up as a new workflow</Button>
      </div>
    </>
  )
}

function RowItem({ row, index, rows, onChange, onDrop }: { row: Row; index: number; rows: readonly Row[]; onChange: (text: string) => void; onDrop: () => void }) {
  const [editing, setEditing] = useState(false)
  const [typed, setTyped] = useState(row.text)
  const field = useRef<HTMLInputElement>(null)
  const fix = useRef<HTMLButtonElement>(null)
  const back = useRef(false)
  useEffect(() => {
    if (editing) field.current?.focus()
    else if (back.current) {
      back.current = false
      fix.current?.focus()
    }
  }, [editing])
  const label = ROW_LABEL[row.kind]
  const inputId = `row-${index}-text`
  const close = (save: boolean) => {
    if (save) onChange(typed)
    back.current = true
    setEditing(false)
  }
  const keys = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      close(true)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      close(false)
    }
  }
  const asked = row.state === 'edited' && row.planner?.text ? `Your request said: “${row.planner.text}”.` : row.note
  return (
    <li className={styles['row']} data-state={row.state}>
      <span className={styles['rowLabel']} id={`row-${index}-label`}>
        {label}
      </span>
      <span className={styles['schip']} data-state={row.state} title={HINT[row.state].charAt(0).toUpperCase() + HINT[row.state].slice(1)}>
        {row.text || 'Not said'}
        <span className="visually-hidden">, {HINT[row.state]}</span>
      </span>
      {editing ? null : (
        <span className={styles['rowButtons']}>
          <button
            ref={fix}
            id={fixId(index)}
            type="button"
            className={styles['small']}
            aria-describedby={`row-${index}-label`}
            onClick={() => {
              setTyped(row.text)
              setEditing(true)
            }}
          >
            {row.state === 'missing' ? 'Fill in' : 'Change'}
          </button>
          {row.state === 'cant_do' && canDrop(rows, index) ? (
            <button type="button" className={styles['small']} aria-describedby={`row-${index}-label`} onClick={onDrop}>
              Leave it out
            </button>
          ) : null}
        </span>
      )}
      {row.state === 'checking' ? (
        <span className={styles['rowNote']}>
          <span className={styles['spin']} aria-hidden="true" />
          <span>Checking your new words</span>
        </span>
      ) : asked ? (
        <span className={styles['rowNote']}>
          {row.state === 'cant_do' || row.state === 'missing' ? <IconAlert size={16} /> : row.state === 'edited' ? <IconPencil size={16} /> : <IconInfo size={16} />}
          <span>{asked}</span>
        </span>
      ) : null}
      {editing ? (
        <span className={styles['rowEdit']}>
          <label className="visually-hidden" htmlFor={inputId}>
            {label}
          </label>
          <input ref={field} id={inputId} type="text" value={typed} maxLength={200} onChange={(event) => setTyped(event.target.value)} onKeyDown={keys} />
          <Button variant="primary" onClick={() => close(true)}>
            Save
          </Button>
          <Button onClick={() => close(false)}>Cancel</Button>
        </span>
      ) : null}
    </li>
  )
}

function AgentSteps({ agent, kinds }: { agent: PlanAgent; kinds: ToolKinds }) {
  return (
    <ol className={styles['steps']} aria-label={`What ${agent.name} does`}>
      {agent.blocks.map((block, index) => {
        const tag = tagOf(block.tool, kinds)
        return (
          <li key={`${String(index)}:${block.say}`}>
            <span>{block.say}</span>
            <span className={styles['tag']} data-writes={tag.writes || undefined}>
              {tag.words}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function Values({ form, agents, shown, onValue }: { form: Form; agents: readonly PlanAgent[]; shown: boolean; onValue: (key: string, value: string) => void }) {
  const inputs = agents.flatMap((agent) => agent.inputs.map((input) => ({ agent, input })))
  if (inputs.length === 0) return null
  return (
    <div className={styles['inputs']}>
      {inputs.map(({ agent, input }) => {
        const id = valueId(agent.index, input.name)
        const value = valueOf(form, agent, input.name)
        const problem = valueProblem(input.kind, value)
        const said = shown || value !== '' ? problem : null
        return (
          <div key={id} className={styles['field']}>
            <label htmlFor={id}>{input.name}</label>
            <input
              id={id}
              type="text"
              value={value}
              aria-invalid={said ? true : undefined}
              aria-describedby={said ? `${id}-help ${id}-error` : `${id}-help`}
              onChange={(event) => onValue(valueKey(agent.index, input.name), event.target.value)}
            />
            <span className={styles['help']} id={`${id}-help`}>
              {input.what}
            </span>
            {said ? (
              <span className={styles['error']} id={`${id}-error`}>
                {said}
              </span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function PlanPanel({ form, plan, kinds, ready, shown, onValue }: { form: Form; plan: PlanState; kinds: ToolKinds; ready: boolean; shown: boolean; onValue: (key: string, value: string) => void }) {
  let body
  if (!ready) body = <p className={styles['note']}>I’ll plan the steps once every part is clear.</p>
  else if (plan.pending)
    body = (
      <p className={styles['actions']} role="status">
        <span className={styles['spin']} aria-hidden="true" />
        Planning the steps
      </p>
    )
  else if (plan.error !== null || plan.view?.kind === 'trouble')
    body = (
      <>
        <p role="alert">{plan.error ?? (plan.view?.kind === 'trouble' ? plan.view.message : '')}</p>
        <div className={styles['actions']}>
          <Button onClick={plan.retry}>Try again</Button>
        </div>
      </>
    )
  else if (plan.view?.kind === 'cannot')
    body = (
      <ul className={styles['problems']}>
        <li>
          <IconAlert size={16} />
          <span>I can’t set this up. {plan.view.reason}</span>
        </li>
        {plan.view.missing.length > 0 ? (
          <li>
            <IconAlert size={16} />
            <span>It would need: {plan.view.missing.join(', ')}.</span>
          </li>
        ) : null}
      </ul>
    )
  else if (plan.view?.kind === 'agents') {
    const view = plan.view
    const drafted = view.agents.filter((agent) => agent.card.kind === 'drafted')
    const fresh = drafted.filter((agent) => !plan.reused.has(agent.index)).map((agent) => agent.name)
    const reused = drafted.filter((agent) => plan.reused.has(agent.index)).map((agent) => agent.name)
    body = (
      <>
        {view.agents.map((agent) => (
          <AgentSteps key={agent.index} agent={agent} kinds={kinds} />
        ))}
        <p className={styles['note']}>
          Done by: {view.agents.map((agent) => agent.name).join(' and ')}. Nothing is changed without an Approver’s yes.
          {fresh.length > 0 ? ` ${fresh.join(' and ')} is a new agent. It’s saved to the Agent library when you turn this workflow on.` : ''}
          {reused.length > 0 ? ` You already saved ${reused.join(' and ')} in the Agent library, so this workflow uses it.` : ''}
        </p>
        {view.problems.length > 0 || view.notIncluded.length > 0 ? (
          <ul id={PROBLEMS_ID} className={styles['problems']} tabIndex={-1}>
            {view.problems.map((problem) => (
              <li key={problem}>
                <IconAlert size={16} />
                <span>{problem}</span>
              </li>
            ))}
            {view.notIncluded.length > 0 ? (
              <li>
                <IconAlert size={16} />
                <span>Left out, because no tool does it yet: {view.notIncluded.join(', ')}.</span>
              </li>
            ) : null}
          </ul>
        ) : null}
        <Values form={form} agents={view.agents} shown={shown} onValue={onValue} />
      </>
    )
  }
  return (
    <section className={styles['panel']} aria-labelledby="plan-h">
      <h2 id="plan-h" tabIndex={-1}>
        What the workflow will do
      </h2>
      {body}
    </section>
  )
}

interface StepCheckProps {
  readonly form: Form
  readonly plan: PlanState
  readonly onChangeRow: (index: number, text: string) => void
  readonly onDropRow: (index: number) => void
  readonly onValue: (key: string, value: string) => void
  readonly onBack: () => void
  readonly onNext: () => void
  readonly onCarryOn: () => void
}

function firstBlocked(form: Form, plan: PlanView | null, rowIndex: number | undefined): HTMLElement | null {
  if (rowIndex !== undefined) return document.getElementById(fixId(rowIndex))
  if (plan?.kind !== 'agents') return document.getElementById('plan-h')
  if (plan.problems.length > 0 || plan.notIncluded.length > 0) return document.getElementById(PROBLEMS_ID)
  for (const agent of plan.agents)
    for (const input of agent.inputs) if (valueProblem(input.kind, valueOf(form, agent, input.name)) !== null) return document.getElementById(valueId(agent.index, input.name))
  return null
}

export function StepCheck({ form, plan, onChangeRow, onDropRow, onValue, onBack, onNext, onCarryOn }: StepCheckProps) {
  const [shown, setShown] = useState(false)
  const tools = useTools()
  if (form.redirect) return <WatchlistStep redirect={form.redirect} onBack={onBack} onCarryOn={onCarryOn} />
  const blockers = nextBlockers(form, plan.view)
  const ready = blockers.rows.length === 0
  const blank = form.rows.every((row) => row.text === '' && row.planner === null)
  const unsure = form.rows.some((row) => row.state === 'missing' || row.state === 'cant_do' || row.state === 'checking')
  const words = blank
    ? 'Tell me each part in a few words, and I’ll set it up as a new workflow.'
    : unsure
      ? 'Here’s what I understood. I’ve marked what I wasn’t sure about or can’t do. Please sort those out before you carry on.'
      : 'Here’s what I understood, and the plan that follows from it. Please check it matches what you meant.'
  const pointAtBlocker = () => {
    setShown(true)
    firstBlocked(form, plan.view, blockers.rows[0]?.index)?.focus()
  }
  return (
    <>
      <div className={styles['body']}>
        <PlannerSays>{words}</PlannerSays>
        <section className={styles['panel']} aria-labelledby="asked-h">
          <h2 id="asked-h">What you asked for</h2>
          <blockquote className={styles['asked']}>
            <span>Your words</span>
            {form.text}
          </blockquote>
          <ul className={styles['rows']} aria-label="What I understood">
            {form.rows.map((row, index) => (
              <RowItem key={`${String(index)}:${row.kind}`} row={row} index={index} rows={form.rows} onChange={(text) => onChangeRow(index, text)} onDrop={() => onDropRow(index)} />
            ))}
          </ul>
          <p className={styles['note']}>Green: from your words. Teal: changed by you. Amber: please fill in. Red: can’t do this yet. Your words stay as you wrote them.</p>
        </section>
        <PlanPanel form={form} plan={plan} kinds={new Map((tools.data ?? []).map((tool) => [tool.id, tool.kind]))} ready={ready} shown={shown} onValue={onValue} />
      </div>
      <div className={styles['foot']}>
        <Button onClick={onBack}>Back</Button>
        <span className={styles['actions']}>
          {blockers.words ? (
            <span className={styles['note']} id="next-why">
              {blockers.words}
            </span>
          ) : null}
          <NextButton blocked={blockers.words !== ''} describedBy="next-why" onNext={onNext} onBlocked={pointAtBlocker} />
        </span>
      </div>
    </>
  )
}
