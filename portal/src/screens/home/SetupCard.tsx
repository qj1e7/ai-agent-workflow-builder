import { useQueryClient } from '@tanstack/react-query'
import { useContext, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'
import { Link } from '../../ui/Link'
import { useChatNavigate } from '../../ui/fromChat'
import { useErrorWords, useSession } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { refusedWords, useCheckPart, useDeleteDraft, usePlanFor, useReadAgentCards, useSaveDraft } from '../../api/plannerQueries'
import { useAgentCards, useCreateAgentUseCase, useMe, useSaveCard, useStartRun, useTools, useUseCase } from '../../api/queries'
import type { DraftView, SimilarWorkflow, ToolId, ToolView, UseCaseView } from '../../api/types'
import { AgentFace } from '../../ui/AgentFace'
import { Button, buttonClassName } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { systemOf } from '../agents/agents'
import { runWhen, timesZone } from '../workflows/workflow'
import { AskTheTeam } from './AskTheTeam'
import { ROW_LABEL, TAG_CHOICE, TAG_FILLED } from './answers'
import {
  afterPartCheck,
  canDrop,
  changeRow,
  DEST_WORDS,
  draftContent,
  dropRow,
  andList,
  leftWords,
  lowerFirst,
  nameProblem,
  nameOf,
  planView,
  reusedAgents,
  cardBlockers,
  savedCopyOf,
  setupLeft,
  taskWithoutSchedule,
  turnOn,
  valueKey,
  valueOf,
  valueProblem,
  whenProblems,
  whenSaid,
  type Often,
  type Planned,
  type PlanAgent,
  type PlanView,
  type Row,
  type Weekday,
  type When,
  type WhenField,
  type Form,
} from './card'
import { DiscardDialog } from '../workflows/Sections'
import { CardMemoryContext } from './cardMemory'
import { CardLive, useMainButton } from './primary'
import styles from './SetupCard.module.css'

/** Where a set-up card starts: the Planner's rows, or a saved draft. */
export interface CardStart {
  readonly form: Form
  readonly plan: Planned | null
  readonly draftId: string | null
  /** The saved draft this card was reopened from, so Never mind can ask and Undo can put it back. */
  readonly resumed?: DraftView
  readonly similar: SimilarWorkflow | null
}

const SAVE_PAUSE_MS = 800
const PROMISES = 'You can pause, change or delete it at any time. If it stops, the AI troubleshooter tells you why.'
const DEST_ASK = 'Other places for a workflow’s result'

const OFTEN: readonly (readonly [Exclude<Often, ''>, string])[] = [
  ['every_day', 'Every day'],
  ['weekdays', 'Every weekday'],
  ['week', 'Every week'],
]
const DAYS: readonly (readonly [Weekday, string])[] = [
  ['monday', 'Monday'],
  ['tuesday', 'Tuesday'],
  ['wednesday', 'Wednesday'],
  ['thursday', 'Thursday'],
  ['friday', 'Friday'],
  ['saturday', 'Saturday'],
  ['sunday', 'Sunday'],
]

const HINT: Record<Row['state'], string> = {
  understood: 'your words',
  changed: 'filled in by me',
  edited: 'changed by you',
  missing: 'please choose',
  cant_do: 'can’t do this yet',
  checking: 'checking your new words',
}
const NOT_SAID: Record<Row['kind'], string> = { schedule: 'when it runs', look_for: 'what to look for', do: 'what it does', where: 'where it goes' }

type ToolKinds = ReadonlyMap<ToolId, ToolView['kind']>

function tagOf(tool: ToolId | null, kinds: ToolKinds): { readonly words: string; readonly writes: boolean } {
  if (tool === null) return { words: 'No system access', writes: false }
  return kinds.get(tool) === 'read' ? { words: `Reads ${systemOf(tool)}`, writes: false } : { words: 'Writes after a yes', writes: true }
}

function writesOf(plan: PlanView | null, kinds: ToolKinds): boolean | null {
  if (plan?.kind !== 'agents' || kinds.size === 0) return null
  return plan.agents.some((agent) => agent.blocks.some((block) => block.tool !== null && kinds.get(block.tool) !== 'read'))
}

/** A part reads inside a sentence, so its first letter drops to lower case, except for a name. */
export const soften = (text: string): string => lowerFirst(text)

function Chip({ row, index, open, editorId, onOpen }: { row: Row; index: number; open: boolean; editorId: string; onOpen: (index: number) => void }) {
  const label = ROW_LABEL[row.kind]
  const shown = row.text === '' ? NOT_SAID[row.kind] : soften(row.text)
  return (
    <button
      type="button"
      id={`${editorId}-chip-${index}`}
      className={styles['chip']}
      data-state={row.state}
      data-kind={row.kind}
      aria-expanded={open}
      aria-controls={open ? editorId : undefined}
      title={HINT[row.state].charAt(0).toUpperCase() + HINT[row.state].slice(1)}
      onClick={() => onOpen(index)}
    >
      {row.state === 'checking' ? <span className={styles['spin']} aria-hidden="true" /> : null}
      {shown}
      <span className="visually-hidden">
        . {label}, {HINT[row.state]}. Change
      </span>
    </button>
  )
}

function Editor({ id, label, row, onSave, onCancel }: { id: string; label: string; row: Row; onSave: (text: string) => void; onCancel: () => void }) {
  const [typed, setTyped] = useState(row.text)
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => field.current?.focus(), [])
  const keys = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      onSave(typed)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
    }
  }
  return (
    <div className={styles['editor']} id={id} role="group" aria-label={`Change ${label}`}>
      <label htmlFor={`${id}-text`}>{label}</label>
      <input ref={field} id={`${id}-text`} type="text" value={typed} maxLength={200} onChange={(event) => setTyped(event.target.value)} onKeyDown={keys} />
      <div className={styles['btns']}>
        <Button variant="primary" onClick={() => onSave(typed)}>
          Save
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}

function DestEditor({ id, onDone }: { id: string; onDone: () => void }) {
  const done = useRef<HTMLButtonElement>(null)
  useEffect(() => done.current?.focus(), [])
  return (
    <div className={styles['editor']} id={id} role="group" aria-label="Where the result goes">
      <p>
        <b>One new Jira ticket</b>, created only after an Approver says yes.
      </p>
      <p className="muted">It’s the only place I can put the result today. Other places, such as Teams or email, aren’t built yet.</p>
      <div className={styles['btns']}>
        <Button ref={done} onClick={onDone} onKeyDown={(event) => event.key === 'Escape' && onDone()}>
          Done
        </Button>
        <AskTheTeam capability={DEST_ASK} starter={`I would like a workflow’s result to go somewhere other than a Jira ticket: `} />
      </div>
    </div>
  )
}

function WhenPicker({ when, problems, focus, onWhen, onDone }: { when: When; problems: Partial<Record<WhenField, string>>; focus: boolean; onWhen: (when: When) => void; onDone: () => void }) {
  const id = useId()
  const first = useRef<HTMLSelectElement>(null)
  useEffect(() => {
    if (focus) first.current?.focus()
  }, [focus])
  const leave = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') onDone()
  }
  return (
    <div className={styles['editor']} role="group" aria-label="Change when it runs">
      <div className={styles['fields']}>
        <div className={styles['field']}>
          <label htmlFor={`${id}-often`}>How often</label>
          <select ref={first} id={`${id}-often`} value={when.often} onKeyDown={leave} onChange={(event) => onWhen({ ...when, often: event.target.value as Often })}>
            <option value="">Choose…</option>
            {OFTEN.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        {when.often === 'week' ? (
          <div className={styles['field']}>
            <label htmlFor={`${id}-day`}>Day</label>
            <select id={`${id}-day`} value={when.day} onKeyDown={leave} onChange={(event) => onWhen({ ...when, day: event.target.value as Weekday | '' })}>
              <option value="">Choose…</option>
              {DAYS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className={styles['field']}>
          <label htmlFor={`${id}-at`}>Time, Singapore</label>
          <input id={`${id}-at`} type="time" step={300} value={when.at} aria-invalid={problems.at ? true : undefined} onKeyDown={leave} onChange={(event) => onWhen({ ...when, at: event.target.value })} />
        </div>
      </div>
      {Object.values(problems)[0] ? <p className={styles['problem']}>{Object.values(problems)[0]}</p> : null}
      <div className={styles['btns']}>
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  )
}

function Notes({ form, onDrop }: { form: Form; onDrop: (index: number) => void }) {
  const items = form.rows.flatMap((row, index) => {
    if (row.kind === 'schedule' || row.state === 'checking' || row.state === 'understood') return []
    const note = row.state === 'edited' && row.planner?.text ? `Your request said: “${row.planner.text}”.` : row.note
    return note === null || note.trim() === '' ? [] : [{ row, index, note }]
  })
  if (items.length === 0) return null
  return (
    <ul className={styles['notes']}>
      {items.map(({ row, index, note }) => (
        <li key={`${String(index)}:${row.kind}`} data-state={row.state}>
          <span>
            <b>{ROW_LABEL[row.kind]}:</b> {note}
          </span>
          {row.state === 'cant_do' && canDrop(form.rows, index) ? (
            <button type="button" className={styles['link']} onClick={() => onDrop(index)}>
              Leave it out
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

function Inputs({ form, agents, shown, onValue }: { form: Form; agents: readonly PlanAgent[]; shown: boolean; onValue: (key: string, value: string) => void }) {
  const inputs = agents.flatMap((agent) => agent.inputs.map((input) => ({ agent, input })))
  if (inputs.length === 0) return null
  return (
    <div className={styles['inputs']}>
      {inputs.map(({ agent, input }) => {
        const id = `value-${String(agent.index)}-${input.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
        const key = valueKey(agent.index, input.name)
        const value = valueOf(form, agent, input.name)
        const problem = valueProblem(input.kind, value)
        const said = shown || value !== '' ? problem : null
        const tag = problem !== null ? TAG_CHOICE : form.typed[key] === undefined ? TAG_FILLED : null
        return (
          <div key={id} className={styles['field']}>
            <label htmlFor={id}>
              {input.name}
              {tag ? <span className={styles['tag']} data-state={problem !== null ? 'missing' : 'changed'}>{tag}</span> : null}
            </label>
            <input id={id} type="text" value={value} aria-invalid={said ? true : undefined} aria-describedby={`${id}-help${said ? ` ${id}-error` : ''}`} onChange={(event) => onValue(key, event.target.value)} />
            <span className={styles['help']} id={`${id}-help`}>
              {input.what}
            </span>
            {said ? (
              <span className={styles['problem']} id={`${id}-error`}>
                {said}
              </span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function HowItWorks({ plan, kinds, reused }: { plan: PlanView | null; kinds: ToolKinds; reused: ReadonlySet<number> | null }) {
  let body
  if (plan === null) body = <p className="muted">The Planner is still choosing the agents.</p>
  else if (plan.kind === 'trouble') body = <p role="alert">{plan.message}</p>
  else if (plan.kind === 'cannot') body = <p>I can’t set this up. {plan.reason}</p>
  else
    body = (
      <>
        {plan.agents.map((agent) => (
          <div key={agent.index} className={styles['agent']}>
            <div className={styles['agentHead']}>
              <AgentFace id={agent.card.kind === 'saved' ? agent.card.id : agent.name} display={agent.name} size={28} />
              <b>{agent.name}</b>
              {agent.card.kind === 'drafted' && reused !== null && !reused.has(agent.index) ? (
                <span className={styles['tag']} data-state="changed">
                  New agent, saved under How it works, in Settings, when you turn this on
                </span>
              ) : null}
            </div>
            <ol aria-label={`What ${agent.name} does`}>
              {agent.blocks.map((block, index) => {
                const tag = tagOf(block.tool, kinds)
                return (
                  <li key={`${String(index)}:${block.say}`}>
                    <span>{block.say}</span>
                    <span className={styles['stepTag']} data-writes={tag.writes || undefined}>
                      {tag.words}
                    </span>
                  </li>
                )
              })}
            </ol>
          </div>
        ))}
        {plan.problems.map((problem) => (
          <p key={problem} className={styles['problem']}>
            {problem}
          </p>
        ))}
        {plan.notIncluded.length > 0 ? <p className={styles['problem']}>Left out, because no tool does it yet: {plan.notIncluded.join(', ')}.</p> : null}
      </>
    )
  return (
    <details className={styles['how']}>
      <summary>How this workflow works</summary>
      <div className={styles['howBody']}>{body}</div>
    </details>
  )
}

function Done({ useCaseId, writes, draftKept, newAgents }: { useCaseId: string; writes: boolean | null; draftKept: boolean; newAgents: readonly string[] }) {
  const useCase = useUseCase(useCaseId)
  const start = useStartRun()
  const latch = useLatch()
  const navigate = useChatNavigate()
  const words = useErrorWords()
  const [key] = useState(newIdempotencyKey)
  const [now] = useState(() => new Date())
  const [problem, setProblem] = useState<string | null>(null)
  const testRun = () =>
    latch.run((settled) =>
      start.mutate(
        { useCaseId, idempotencyKey: key, test: true },
        { onSuccess: (started) => navigate(`/runs/${started.run_id}`), onError: (error) => setProblem(words(error)), onSettled: settled },
      ),
    )
  const name = useCase.data?.name
  return (
    <div className={styles['done']} role="status">
      <span className={styles['tick']}>
        <IconCheck size={20} strokeWidth={3} />
      </span>
      <div>
        <p>
          <b>{name ? `${name} is on.` : 'Your workflow is on.'}</b>
        </p>
        {useCase.data ? <p>{firstRun(useCase.data, now)}</p> : null}
        <p>
          {writes === false
            ? 'Nothing it does changes data, so no yes is needed.'
            : 'Before it changes anything, any Approver on your team except you is asked for a yes in Teams.'}
        </p>
        {newAgents.length > 0 ? <p>{newAgents.length === 1 ? `The ${newAgents[0] ?? ''} is saved under How it works, in Settings.` : `${andList(newAgents.map((agent) => `the ${agent}`))} are saved under How it works, in Settings.`}</p> : null}
        <p className="muted">{PROMISES}</p>
        {draftKept ? <p className="muted">Your draft is still on Workflows. This workflow is already on, so there is no need to turn it on again.</p> : null}
        <div className={styles['btns']}>
          <Button variant="primary" loading={start.isPending} onClick={testRun}>
            Do a test run
          </Button>
          <Link to={`/workflows/${encodeURIComponent(useCaseId)}`} className={styles['link']}>
            See it on Workflows
          </Link>
        </div>
        {problem ? (
          <p className={styles['problem']} role="alert">
            {problem}
          </p>
        ) : null}
      </div>
    </div>
  )
}

function firstRun(useCase: UseCaseView, now: Date): string {
  if (useCase.state === 'paused') return 'It is paused.'
  if (!useCase.next_run_at) return 'It runs when an Operator starts it.'
  const zone = useCase.schedule?.time_zone
  const at = runWhen(useCase.next_run_at, now, zone)
  return `First run ${at.startsWith('Today, ') ? `today at ${at.slice('Today, '.length)}` : `on ${at}`}, ${timesZone(zone)}.`
}

export type Phase = { readonly kind: 'open' } | { readonly kind: 'done'; readonly useCaseId: string; readonly draftKept: boolean; readonly newAgents: readonly string[] } | { readonly kind: 'never_mind' }

/**
 * The set-up card (spec 7). One state, the form, drives the sentence, the footer line and the reason Turn it on waits. Every
 * change is saved as a draft after a short pause, so Resume on Workflows reopens it.
 */
export function SetupCard({ start }: { start: CardStart }) {
  const main = useMainButton()
  const live = useContext(CardLive)
  const memory = useContext(CardMemoryContext)
  const session = useSession()
  // The person the card was drawn for. Its draft is theirs, so nothing is saved once someone else has signed in.
  const [owner] = useState(session.cacheScope)
  const [kept] = useState(memory.kept)
  const [form, setForm] = useState(kept?.form ?? start.form)
  const [draft, setDraft] = useState(kept ? kept.draft : start.draftId)
  const [phase, setPhase] = useState<Phase>(kept?.phase ?? { kind: 'open' })
  const [editing, setEditing] = useState<number | 'dest' | 'when' | 'name' | null>(null)
  const [shown, setShown] = useState(false)
  const [refused, setRefused] = useState<readonly string[]>([])
  const [saveProblem, setSaveProblem] = useState<string | null>(null)
  const [filled, setFilled] = useState(true)
  const [asking, setAsking] = useState(false)
  const [discardProblem, setDiscardProblem] = useState<string | null>(null)
  const [undoProblem, setUndoProblem] = useState<string | null>(null)
  const [params, setParams] = useSearchParams()
  const id = useId()
  const check = useCheckPart()
  const saveDraft = useSaveDraft()
  const deleteDraft = useDeleteDraft()
  const saveCard = useSaveCard()
  const readCards = useReadAgentCards()
  const create = useCreateAgentUseCase()
  const library = useAgentCards()
  const me = useMe()
  const tools = useTools()
  const latch = useLatch()
  const words = useErrorWords()
  const queryClient = useQueryClient()
  const cards = useRef(new Map<string, string>())
  const back = useRef<string | null>(null)

  const task = taskWithoutSchedule(form.rows)
  const rowsReady = form.rows.length > 0 && cardBlockers(form.rows).length === 0
  const planned = start.plan?.task === task ? start.plan.answer : undefined
  const planQuery = usePlanFor(task, rowsReady && phase.kind === 'open', planned)
  const plan = useMemo(() => (planQuery.data ? planView(planQuery.data, form.rows) : null), [planQuery.data, form.rows])
  const kinds: ToolKinds = useMemo(() => new Map((tools.data ?? []).map((tool) => [tool.id, tool.kind])), [tools.data])
  const reused = reusedAgents(plan, library.data, me.data?.id)
  const left = setupLeft(form, plan)
  const problems = whenProblems(form.when)
  const timeText = whenSaid(form.when)
  const pickerOpen = editing === 'when' || (timeText === null && left.length === 1 && left[0] === 'when it runs')

  const dirty = useRef(false)
  const turningOn = useRef(false)
  const alive = useRef(true)
  const latest = useRef({ form, plan: null as Planned | null, draft, phase, live })
  useEffect(() => {
    latest.current = { form, plan: planQuery.data ? { task, answer: planQuery.data } : null, draft, phase, live }
  })

  const persist = (onDone?: (saved: string) => void) => {
    const now = latest.current
    if (now.phase.kind !== 'open' || turningOn.current || session.cacheScope() !== owner) return
    const saved = now.draft ?? newIdempotencyKey()
    latest.current = { ...now, draft: saved }
    memory.keep({ form: now.form, draft: saved, phase: now.phase })
    setDraft(saved)
    saveDraft.mutate(
      { draftId: saved, draft: { content: draftContent(now.form, now.plan) } },
      { onSuccess: () => onDone?.(saved), onError: (error) => setSaveProblem(words(error)) },
    )
  }

  useEffect(() => {
    memory.keep({ form, draft, phase })
  })

  const watching = useRef(false)
  useEffect(() => {
    if (phase.kind !== 'open' || !dirty.current) return
    watching.current = true
    const timer = setTimeout(
      () =>
        persist((saved) => {
          setSaveProblem(null)
          if (live && params.get('draft') !== saved) setParams({ draft: saved }, { replace: true })
        }),
      SAVE_PAUSE_MS,
    )
    return () => clearTimeout(timer)
    // The pause restarts on every change to the card or its plan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, planQuery.data])

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      setTimeout(() => {
        if (!alive.current && latest.current.live && latest.current.phase.kind === 'open') persist()
      }, 0)
    }
    // Leaving the page keeps what is on the card as a draft. A card a newer answer replaced was kept when it was replaced.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const wasLive = useRef(live)
  useEffect(() => {
    if (wasLive.current && !live) persist()
    wasLive.current = live
    // A newer answer replaces this card, which is kept as a draft. Drawn again after that, it has nothing new to keep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live])

  useEffect(() => {
    if (editing === 'name') document.getElementById(`${id}-name`)?.focus()
  }, [editing, id])

  useEffect(() => {
    if (editing === null && back.current !== null) {
      document.getElementById(back.current)?.focus()
      back.current = null
    }
  }, [editing])

  const edit = (next: (before: Form) => Form) => {
    dirty.current = true
    setForm(next)
  }

  const checkPart = (part: Pick<Row, 'kind' | 'text'>) => {
    check.mutateAsync({ kind: part.kind, text: part.text }).then(
      (result) => setForm((before) => afterPartCheck(before, part, result)),
      () => setForm((before) => afterPartCheck(before, part, null)),
    )
  }

  const reopened = useRef(false)
  useEffect(() => {
    if (reopened.current) return
    reopened.current = true
    for (const row of start.form.rows) if (row.state === 'checking') checkPart(row)
    // Only the parts a reopened draft sends back are checked here, once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const changePart = (index: number, text: string) => {
    const next = changeRow(form, index, text)
    dirty.current = true
    setForm(next)
    back.current = `${id}-chip-${index}`
    setEditing(null)
    const part = next.rows[index]
    if (part?.state === 'checking') checkPart(part)
  }

  const open = (target: number | 'dest' | 'when' | 'name') => setEditing((now) => (now === target ? null : target))

  const turnItOn = () => {
    if (plan?.kind !== 'agents') return
    const problem = nameProblem(form.name === '' ? nameOf(form, plan) : form.name)
    if (problem) {
      setRefused([problem])
      return
    }
    setRefused([])
    turningOn.current = true
    latch.run((settled) => {
      turnOn(form, plan, draft, cards.current, {
        savedCard: async (card) => (me.data ? savedCopyOf(await readCards(), me.data.id, card) : null),
        saveCard: async (card) => (await saveCard.mutateAsync({ cardId: null, card })).card_id,
        create: (body) => create.mutateAsync(body),
        deleteDraft: (draftId) => deleteDraft.mutateAsync(draftId),
      })
        .then(({ useCaseId, draftKept }) => {
          void queryClient.invalidateQueries({ queryKey: ['home'] })
          void queryClient.invalidateQueries({ queryKey: ['agent-cards'] })
          setPhase({ kind: 'done', useCaseId, draftKept, newAgents: plan.agents.filter((agent) => agent.card.kind === 'drafted' && !(reused?.has(agent.index) ?? false)).map((agent) => agent.name) })
          if (params.get('draft') !== null) setParams({}, { replace: true })
        })
        .catch((error: unknown) => {
          const said = refusedWords(error)
          turningOn.current = false
          setRefused(said.length > 0 ? said : [words(error)])
        })
        .finally(settled)
    })
  }

  const leave = () => {
    setPhase({ kind: 'never_mind' })
    if (params.get('draft') !== null) setParams({}, { replace: true })
  }

  const neverMind = () => {
    if (start.resumed !== undefined && draft !== null) {
      setDiscardProblem(null)
      setAsking(true)
      return
    }
    if (draft !== null) deleteDraft.mutate(draft)
    leave()
  }

  const confirmDiscard = () => {
    if (draft === null) return
    latch.run((settled) =>
      deleteDraft.mutate(draft, {
        onSuccess: () => {
          setAsking(false)
          leave()
        },
        onError: (error) => setDiscardProblem(`Could not discard it. ${words(error)}`),
        onSettled: settled,
      }),
    )
  }

  const undoNeverMind = () => {
    const kept = start.resumed
    if (kept === undefined) return
    latch.run((settled) =>
      saveDraft.mutate(
        { draftId: kept.draft_id, draft: { step: kept.step, content: kept.content, put_back: { created_at: kept.created_at, saved_at: kept.saved_at } } },
        {
          onSuccess: () => {
            setUndoProblem(null)
            setPhase({ kind: 'open' })
            setParams({ draft: kept.draft_id }, { replace: true })
          },
          onError: (error) => setUndoProblem(`Could not put it back. ${words(error)}`),
          onSettled: settled,
        },
      ),
    )
  }

  const pointAtWhatIsLeft = () => {
    setShown(true)
    const row = form.rows.findIndex((r) => r.kind !== 'schedule' && (r.state === 'missing' || r.state === 'cant_do' || r.state === 'checking'))
    if (row >= 0) {
      document.getElementById(`${id}-chip-${row}`)?.focus()
      return
    }
    if (timeText === null) {
      setEditing('when')
      return
    }
    document.querySelector<HTMLElement>(`[data-card="${id}"] input[aria-invalid="true"], [data-card="${id}"] [data-state="missing"] input`)?.focus()
  }

  if (phase.kind === 'never_mind')
    return (
      <div>
        <p className="muted">All right, never mind.</p>
        {start.resumed !== undefined ? (
          <>
            <Button loading={saveDraft.isPending} onClick={undoNeverMind}>
              Undo
            </Button>
            {undoProblem ? (
              <p className={styles['problem']} role="alert">
                {undoProblem}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    )
  if (phase.kind === 'open' && !live) return <p className="muted">Saved as a draft. Open it from Workflows to carry on.</p>
  if (phase.kind === 'done') return <Done useCaseId={phase.useCaseId} writes={writesOf(plan, kinds)} draftKept={phase.draftKept} newAgents={phase.newAgents} />

  const title = nameOf(form, plan) || 'New workflow'
  const rowsOf = (kind: Row['kind']) => form.rows.flatMap((row, index) => (row.kind === kind ? [{ row, index }] : []))
  const chips = (kind: 'look_for' | 'do' | 'where') => {
    const list = rowsOf(kind)
    return list.map(({ row, index }, at) => (
      <span key={index}>
        {at > 0 ? ' and ' : ''}
        <Chip row={row} index={index} open={editing === index} editorId={id} onOpen={open} />
      </span>
    ))
  }
  const editedRow = typeof editing === 'number' ? form.rows[editing] : undefined
  const whyWaiting = left.length > 0
  const sentence = (
    <p className={styles['sentence']}>
      {timeText !== null ? (
        timeText
      ) : (
        <button type="button" className={styles['chip']} data-state="missing" aria-expanded={editing === 'when'} onClick={() => open('when')}>
          Choose when it runs
        </button>
      )}
      {rowsOf('look_for').length > 0 ? <>, find </> : ', '}
      {chips('look_for')}
      {rowsOf('do').length > 0 ? <>, </> : null}
      {chips('do')}
      {rowsOf('where').length > 0 ? <>, </> : null}
      {chips('where')}
      {', and put the result in '}
      <button
        type="button"
        id={`${id}-dest`}
        className={styles['chip']}
        data-state="changed"
        aria-expanded={editing === 'dest'}
        aria-controls={editing === 'dest' ? `${id}-editor` : undefined}
        title="Filled in by me. It’s written after a yes."
        onClick={() => open('dest')}
      >
        {DEST_WORDS}
        <span className="visually-hidden">, filled in by me, written after a yes. Change</span>
      </button>
      .
    </p>
  )

  return (
    <section className={styles['card']} aria-labelledby={`${id}-title`} data-card={id}>
      <div className={styles['head']}>
        {editing === 'name' ? (
          <div className={styles['rename']}>
            <label className="visually-hidden" htmlFor={`${id}-name`}>
              Workflow name
            </label>
            <input
              id={`${id}-name`}
              type="text"
              value={form.name}
              onChange={(event) => {
                setFilled(false)
                edit((before) => ({ ...before, name: event.target.value }))
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === 'Escape') {
                  event.preventDefault()
                  back.current = `${id}-rename`
                  setEditing(null)
                }
              }}
            />
            <Button
              onClick={() => {
                back.current = `${id}-rename`
                setEditing(null)
              }}
            >
              Done
            </Button>
          </div>
        ) : (
          <>
            <h3 id={`${id}-title`}>{title}</h3>
            {filled ? (
              <span className={styles['tag']} data-state="changed">
                {TAG_FILLED}
              </span>
            ) : null}
            <button type="button" id={`${id}-rename`} className={styles['link']} onClick={() => open('name')}>
              Rename<span className="visually-hidden"> {title}</span>
            </button>
          </>
        )}
      </div>

      <div className={styles['part']}>
        <h4>What will happen</h4>
        {sentence}
        {editedRow !== undefined && typeof editing === 'number' ? (
          <Editor id={`${id}-editor`} label={ROW_LABEL[editedRow.kind]} row={editedRow} onSave={(text) => changePart(editing, text)} onCancel={() => ((back.current = `${id}-chip-${editing}`), setEditing(null))} />
        ) : null}
        {editing === 'dest' ? (
          <DestEditor
            id={`${id}-editor`}
            onDone={() => {
              back.current = `${id}-dest`
              setEditing(null)
            }}
          />
        ) : null}
        <Notes form={form} onDrop={(index) => edit((before) => dropRow(before, index))} />
        {start.similar ? (
          <p className={styles['similar']}>
            You already have a workflow with this name. <Link to={`/workflows/${encodeURIComponent(start.similar.use_case_id)}`}>Open {start.similar.name}</Link>
          </p>
        ) : null}
        {plan?.kind === 'agents' ? <Inputs form={form} agents={plan.agents} shown={shown} onValue={(key, value) => edit((before) => ({ ...before, typed: { ...before.typed, [key]: value } }))} /> : null}
        {plan?.kind === 'cannot' ? <p className={styles['problem']}>I can’t set this up. {plan.reason}</p> : null}
        {plan?.kind === 'trouble' || planQuery.isError ? (
          <div>
            <p className={styles['problem']} role="alert">
              {plan?.kind === 'trouble' ? plan.message : planQuery.isError ? words(planQuery.error) : ''}
            </p>
            <Button onClick={() => void planQuery.refetch()}>Try again</Button>
          </div>
        ) : null}
      </div>

      <div className={styles['part']}>
        <h4>When</h4>
        <p className={styles['whenLine']}>
          {timeText !== null ? (
            <span>{timeText}, Singapore time</span>
          ) : (
            <span className={styles['chip']} data-state="missing">
              Choose when it runs
            </span>
          )}
          <Button aria-expanded={pickerOpen} onClick={() => setEditing((now) => (now === 'when' && timeText !== null ? null : 'when'))}>
            Change<span className="visually-hidden"> when it runs</span>
          </Button>
        </p>
        {pickerOpen ? (
          <WhenPicker
            when={form.when}
            problems={shown || form.when.often !== '' || form.when.at !== '' ? problems : {}}
            focus={editing === 'when'}
            onWhen={(when) => edit((before) => ({ ...before, when }))}
            onDone={() => setEditing(null)}
          />
        ) : null}
      </div>

      <div className={styles['part']}>
        <h4>What needs a yes</h4>
        <p>
          {writesOf(plan, kinds) === false
            ? 'Nothing in this workflow changes data, so it needs no yes.'
            : 'Anything that changes data, such as creating the Jira ticket, waits for a yes in Teams on each run. Any Approver on your team except you can say yes.'}
        </p>
      </div>

      <HowItWorks plan={plan} kinds={kinds} reused={reused} />

      <div className={styles['foot']}>
        <button
          type="button"
          className={buttonClassName(main)}
          aria-describedby={`${id}-left`}
          aria-busy={create.isPending || saveCard.isPending || undefined}
          onClick={whyWaiting ? pointAtWhatIsLeft : turnItOn}
        >
          Turn it on
        </button>
        <span className={styles['left']} id={`${id}-left`}>
          {leftWords(left)}
        </span>
        <button type="button" className={styles['link']} onClick={neverMind}>
          Never mind
        </button>
      </div>
      {refused.length > 0 ? (
        <ul className={styles['refused']} role="alert">
          {refused.map((said) => (
            <li key={said}>{said}</li>
          ))}
        </ul>
      ) : null}
      {saveProblem ? (
        <p className={styles['problem']} role="alert">
          {saveProblem}
        </p>
      ) : null}
      {asking ? <DiscardDialog name={title} busy={deleteDraft.isPending} problem={discardProblem} onClose={() => setAsking(false)} onConfirm={confirmDiscard} /> : null}
    </section>
  )
}
