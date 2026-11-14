import { useQueryClient } from '@tanstack/react-query'
import { useContext, useEffect, useId, useMemo, useReducer, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { useErrorWords, useSession } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { refusedWords, useCheckPart, useDeleteDraft, usePlanFor, useReadAgentCards, useSaveDraft } from '../../api/plannerQueries'
import { useAgentCards, useMe, useSaveCard, useTools, useWatchlist } from '../../api/queries'
import { useSetUpOff } from '../../api/workflowQueries'
import type { DraftView, InputKind, SimilarWorkflow, ToolId, ToolView } from '../../api/types'
import { Button, buttonClassName } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { AskTheTeam } from './AskTheTeam'
import { AlreadyHave } from './AlreadyHave'
import { Building, DraftPill } from './Building'
import {
  afterPartCheck,
  answerWhen,
  cardPhase,
  ASK_DAYS,
  canDrop,
  changeRow,
  draftContent,
  dropRow,
  leftWords,
  lowerFirst,
  nameProblem,
  nameOf,
  nextQuestion,
  planView,
  reusedAgents,
  cardBlockers,
  savedCopyOf,
  secondName,
  setUp,
  setUpWords,
  setupLeft,
  taskWithoutSchedule,
  valueKey,
  valueOf,
  valueProblem,
  whenProblems,
  whenSaid,
  type Often,
  type Planned,
  type PlanAgent,
  type PlanView,
  type Question,
  type Row,
  type Weekday,
  type When,
  type WhenField,
  type Form,
  type CardPhase,
} from './card'
import { DiscardDialog } from '../workflows/Sections'
import { CardMemoryContext } from './cardMemory'
import { ASKED_NEXT, partMark, type Mark } from './parts'
import { crossParts, PartsList, type Part } from './PartsList'
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

/** The sketch's three parts of a request: what it watches, when, and what it does then. Where the result goes is part of Then. */
export type PartKey = 'Watch' | 'When' | 'Then'
const PART_OF: Readonly<Record<Row['kind'], PartKey>> = { schedule: 'When', look_for: 'Watch', do: 'Then', where: 'Then' }
/** A value an agent needs belongs to the part it serves: the Jira project to Then, anything it reads to Watch. */
const inputPart = (kind: InputKind): PartKey => (kind === 'jira_project' ? 'Then' : 'Watch')

type ToolKinds = ReadonlyMap<ToolId, ToolView['kind']>

function writesOf(plan: PlanView | null, kinds: ToolKinds): boolean | null {
  if (plan?.kind !== 'agents' || kinds.size === 0) return null
  return plan.agents.some((agent) => agent.blocks.some((block) => block.tool !== null && kinds.get(block.tool) !== 'read'))
}

/** A part reads inside a sentence, so its first letter drops to lower case, except for a name. */
export const soften = (text: string): string => lowerFirst(text)

const upperFirst = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1)

function Chip({ row, index, open, editorId, onOpen }: { row: Row; index: number; open: boolean; editorId: string; onOpen: (index: number) => void }) {
  const shown = row.text === '' ? NOT_SAID[row.kind] : upperFirst(row.text)
  return (
    <button
      type="button"
      id={`${editorId}-chip-${index}`}
      className={styles['chip']}
      data-state={row.state}
      data-kind={row.kind}
      aria-expanded={open}
      aria-controls={open ? editorId : undefined}
      title={upperFirst(HINT[row.state])}
      onClick={() => onOpen(index)}
    >
      {row.state === 'checking' ? <span className={styles['spin']} aria-hidden="true" /> : null}
      {shown}
      <span className="visually-hidden">
        . {PART_OF[row.kind]}, {HINT[row.state]}. Change
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

function WhenPicker({ when, problems, focus, onWhen, onDone }: { when: When; problems: Partial<Record<WhenField, string>>; focus: boolean; onWhen: (when: When) => void; onDone: () => void }) {
  const id = useId()
  const first = useRef<HTMLSelectElement>(null)
  useEffect(() => {
    if (focus) first.current?.focus()
  }, [focus])
  const leave = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    onDone()
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

/** One of the card's three parts, from the pieces that belong to it. A part with nothing in it is left off. */
function keyed(key: PartKey, pieces: readonly { readonly mark: Mark; readonly body: ReactNode }[]): Part[] {
  if (pieces.length === 0) return []
  return [{ key, mark: partMark(pieces.map((piece) => piece.mark)), label: key, body: pieces.map((piece, at) => <span key={at} className={styles['piece']}>{piece.body}</span>) }]
}

/** The parts once Set up is pressed: what it watches, when and what it does then, as words, each a tick. A value already in the words isn't said again. */
export function frozenParts(form: Form, plan: PlanView | null, writes: boolean | null, youRun: string | null): Part[] {
  const project = plan?.kind === 'agents' && plan.agents.some((agent) => agent.inputs.some((input) => input.kind === 'jira_project'))
  // Where it goes is said once: by the Jira project it was set up with, when an agent has one.
  const shown = (row: Row) => row.kind !== 'schedule' && row.text !== '' && !(row.kind === 'where' && project)
  const texts = (part: PartKey) => form.rows.filter((row) => shown(row) && PART_OF[row.kind] === part).map((row) => upperFirst(row.text))
  const said = (part: PartKey, value: string) => texts(part).some((text) => text.toLowerCase().includes(value.toLowerCase()))
  const values = (part: PartKey) =>
    plan?.kind === 'agents'
      ? plan.agents.flatMap((agent) =>
          agent.inputs.filter((input) => inputPart(input.kind) === part && !said(part, valueOf(form, agent, input.name))).map((input) => `${input.name}: ${valueOf(form, agent, input.name)}`),
        )
      : []
  const line = (part: PartKey, extra: readonly string[] = []) => [...texts(part), ...values(part), ...extra].map((text) => ({ mark: 'ok' as const, body: text }))
  return [
    ...keyed('Watch', line('Watch', youRun ? [`You run ${youRun}`] : [])),
    ...keyed('When', [{ mark: 'ok', body: whenSaid(form.when) ?? '' }]),
    ...keyed('Then', line('Then', writes === false ? [] : ['After a yes'])),
  ]
}

export type Phase = CardPhase

/**
 * The set-up card, in the sketch's shape: what it understood as Watch, When and Then, a cross for each part it can't do, and one
 * question at a time. Every change is saved as a draft after a short pause, so Resume on Workflows reopens it. Set up makes the
 * workflow as a draft, and the card goes on to build, test and turn it on.
 */
export function SetupCard({ start }: { start: CardStart }) {
  if (start.similar) return <AlreadyHave similar={start.similar} card={<SettingUp start={{ ...start, form: { ...start.form, name: secondName(start.form.name || start.similar.name) } }} />} />
  return <SettingUp start={start} />
}

function SettingUp({ start }: { start: CardStart }) {
  const main = useMainButton()
  const live = useContext(CardLive)
  const memory = useContext(CardMemoryContext)
  const session = useSession()
  // The person the card was drawn for. Its draft is theirs, so nothing is saved once someone else has signed in.
  const [owner] = useState(session.cacheScope)
  const [kept] = useState(memory.kept)
  const [form, setForm] = useState(kept?.form ?? start.form)
  const [draft, setDraft] = useState(kept ? kept.draft : start.draftId)
  const [phase, act] = useReducer(cardPhase, kept?.phase ?? { kind: 'open' })
  const [editing, setEditing] = useState<number | 'when' | null>(null)
  const [shown, setShown] = useState(false)
  const [refused, setRefused] = useState<readonly string[]>([])
  const [saveProblem, setSaveProblem] = useState<string | null>(null)
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
  const create = useSetUpOff()
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
  const question = nextQuestion(form, plan)
  const problems = whenProblems(form.when)
  const timeText = whenSaid(form.when)
  const writes = writesOf(plan, kinds)
  const repo = plan?.kind === 'agents' ? plan.agents.flatMap((agent) => agent.inputs.filter((input) => input.kind === 'github_repo').map((input) => valueOf(form, agent, input.name)))[0] : undefined
  const watched = useWatchlist({ enabled: repo !== undefined })
  const youRun = (repo && watched.data?.software.find((row) => row.source.ref.toLowerCase() === repo.toLowerCase())?.our_version) ?? null

  const dirty = useRef(false)
  const settingUp = useRef(false)
  const alive = useRef(true)
  const latest = useRef({ form, plan: null as Planned | null, draft, phase, live })
  useEffect(() => {
    latest.current = { form, plan: planQuery.data ? { task, answer: planQuery.data } : null, draft, phase, live }
  })

  const persist = (onDone?: (saved: string) => void) => {
    const now = latest.current
    if (now.phase.kind !== 'open' || settingUp.current || session.cacheScope() !== owner) return
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

  useEffect(() => {
    if (phase.kind !== 'open' || !dirty.current) return
    const timer = setTimeout(
      () =>
        persist((saved) => {
          setSaveProblem(null)
          // Read when the save lands, not when it started: a newer answer may have replaced this card since, and its address is the chat's.
          if (latest.current.live && params.get('draft') !== saved) setParams({ draft: saved }, { replace: true })
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
    if (editing === null && back.current !== null) {
      document.getElementById(back.current)?.focus()
      back.current = null
    }
  }, [editing])

  const edit = (next: (before: Form) => Form) => {
    dirty.current = true
    setForm(next)
  }

  // After a choice, focus moves on to the next question, or to the button once nothing is left to ask.
  const focusNext = useRef(false)
  useEffect(() => {
    if (!focusNext.current) return
    focusNext.current = false
    const next = document.querySelector<HTMLElement>(`[data-card="${id}"] [data-mark="ask"] :is(button, input)`) ?? document.getElementById(`${id}-set-up`)
    next?.focus()
  })

  const leaveOut = (index: number) => edit((before) => dropRow(before, index))

  const choose = (set: Partial<When>) => {
    focusNext.current = true
    edit((before) => answerWhen(before, set))
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

  const open = (target: number | 'when') => setEditing((now) => (now === target ? null : target))

  const pressSetUp = () => {
    if (plan?.kind !== 'agents') return
    const problem = nameProblem(nameOf(form, plan))
    if (problem) {
      setRefused([problem])
      return
    }
    setRefused([])
    settingUp.current = true
    act({ type: 'set_up' })
    latch.run((settled) => {
      setUp(form, plan, draft, cards.current, {
        savedCard: async (card) => (me.data ? savedCopyOf(await readCards(), me.data.id, card) : null),
        saveCard: async (card) => (await saveCard.mutateAsync({ cardId: null, card })).card_id,
        create: (body) => create.mutateAsync(body),
        deleteDraft: (draftId) => deleteDraft.mutateAsync(draftId),
      })
        .then(({ useCaseId, draftKept }) => {
          void queryClient.invalidateQueries({ queryKey: ['home'] })
          void queryClient.invalidateQueries({ queryKey: ['agent-cards'] })
          const newAgents = plan.agents.filter((agent) => agent.card.kind === 'drafted' && !(reused?.has(agent.index) ?? false)).map((agent) => agent.name)
          memory.keep({ form, draft: null, phase: { kind: 'built', useCaseId, draftKept, newAgents } })
          act({ type: 'built', useCaseId, draftKept, newAgents })
          if (params.get('draft') !== null) setParams({}, { replace: true })
        })
        .catch((error: unknown) => {
          const said = refusedWords(error)
          settingUp.current = false
          act({ type: 'refused' })
          setRefused(said.length > 0 ? said : [words(error)])
        })
        .finally(settled)
    })
  }

  const leave = () => {
    act({ type: 'never_mind' })
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
    const before = start.resumed
    if (before === undefined) return
    latch.run((settled) =>
      saveDraft.mutate(
        { draftId: before.draft_id, draft: { step: before.step, content: before.content, put_back: { created_at: before.created_at, saved_at: before.saved_at } } },
        {
          onSuccess: () => {
            setUndoProblem(null)
            act({ type: 'undo' })
            setParams({ draft: before.draft_id }, { replace: true })
          },
          onError: (error) => setUndoProblem(`Could not put it back. ${words(error)}`),
          onSettled: settled,
        },
      ),
    )
  }

  // A question first, since the footer counts questions. Else the part she must change.
  const pointAtWhatIsLeft = () => {
    setShown(true)
    const asked = document.querySelector<HTMLElement>(`[data-card="${id}"] [data-mark="ask"] :is(button, input)`)
    const row = form.rows.findIndex((r) => r.kind !== 'schedule' && (r.state === 'cant_do' || r.state === 'checking'))
    ;(asked ?? (row >= 0 ? document.getElementById(`${id}-chip-${row}`) : null))?.focus()
  }

  const title = nameOf(form, plan) || 'New workflow'
  const crosses = crossParts(
    form.marked.filter((part) => part.mark === 'cant'),
    { when: form.when, short: true },
    (part) => (part.reason === 'cant_do' ? <AskTheTeam capability={part.text} starter={`I asked the Planner for: ${form.text}\n\nWhat it can't do yet: ${part.text}`} /> : null),
  )

  if (phase.kind === 'dropped')
    return (
      <div data-card={id}>
        <Card title={title} pill={<DraftPill label="Dropped" tone="quiet" />} status={<span role="status">Nothing was set up.</span>} actions={start.resumed !== undefined ? <Button loading={saveDraft.isPending} onClick={undoNeverMind}>Undo</Button> : undefined}>
          {undoProblem ? (
            <p className={styles['problem']} role="alert">
              {undoProblem}
            </p>
          ) : null}
        </Card>
      </div>
    )
  if (phase.kind === 'built')
    return (
      <div data-card={id}>
        <Building useCaseId={phase.useCaseId} title={title} parts={[...frozenParts(form, plan, writes, youRun), ...crosses]} newAgents={phase.newAgents} draftKept={phase.draftKept} />
      </div>
    )
  if (!live) return <p className="muted">Saved as a draft. Open it from Workflows to carry on.</p>

  const creating = phase.kind === 'creating'
  const asked = (words: string, body: ReactNode) => (
    <>
      <span className={styles['pq']} id={`${id}-q`}>
        {words}
      </span>
      {body}
    </>
  )
  const chipOf = (row: Row, index: number) => <Chip row={row} index={index} open={editing === index} editorId={id} onOpen={open} />
  const editorOf = (index: number) => {
    const row = form.rows[index]
    if (editing !== index || row === undefined) return null
    const close = () => {
      back.current = `${id}-chip-${index}`
      setEditing(null)
    }
    return <Editor id={`${id}-editor`} label={PART_OF[row.kind]} row={row} onSave={(text) => changePart(index, text)} onCancel={close} />
  }
  const noteOf = (row: Row): string | null => (row.state === 'edited' && row.planner?.text ? `Your request said: “${row.planner.text}”.` : row.state === 'changed' || row.state === 'cant_do' ? row.note : null)
  const askedRow = (q: Question | null, index: number): q is Extract<Question, { kind: 'row' }> => q?.kind === 'row' && q.index === index

  const picker =
    editing === 'when' ? (
      <WhenPicker
        when={form.when}
        problems={shown || form.when.often !== '' || form.when.at !== '' ? problems : {}}
        focus
        onWhen={(when) => edit((before) => ({ ...before, when }))}
        onDone={() => setEditing(null)}
      />
    ) : null
  const whenPiece =
    question?.kind === 'when'
      ? {
          mark: 'ask' as const,
          body: asked(
            question.words,
            <>
              <span className={styles['pick']} role="group" aria-labelledby={`${id}-q`}>
                {question.choices.map((choice) => (
                  <button key={choice.label} type="button" className={styles['choice']} onClick={() => choose(choice.set)}>
                    {choice.label}
                  </button>
                ))}
                {question.field === 'at' ? (
                  <button type="button" className={styles['choice']} aria-expanded={editing === 'when'} onClick={() => open('when')}>
                    Another time
                  </button>
                ) : null}
              </span>
              {picker}
            </>,
          ),
        }
      : {
          mark: 'ok' as const,
          body: (
            <>
              <span>{timeText ?? ''}, Singapore time</span>
              <button type="button" className={styles['link']} aria-expanded={editing === 'when'} onClick={() => open('when')}>
                Change<span className="visually-hidden"> when it runs</span>
              </button>
              {picker}
            </>
          ),
        }

  const rowPiece = (row: Row, index: number): { readonly mark: Mark; readonly body: ReactNode } => {
    if (row.state === 'missing')
      return askedRow(question, index) ? { mark: 'ask', body: asked(question.words, <>{chipOf(row, index)}{editorOf(index)}</>) } : { mark: 'later', body: <span className="muted">{ASKED_NEXT}</span> }
    const note = noteOf(row)
    return {
      mark: row.state === 'cant_do' ? 'no' : row.state === 'checking' ? 'later' : 'ok',
      body: (
        <>
          {chipOf(row, index)}
          {note ? <span className={styles['pnote']}>{note}</span> : null}
          {row.state === 'cant_do' && canDrop(form.rows, index) ? (
            <button type="button" className={styles['link']} onClick={() => leaveOut(index)}>
              Leave it out
            </button>
          ) : null}
          {editorOf(index)}
        </>
      ),
    }
  }

  const rowPieces = (part: PartKey) => form.rows.flatMap((row, index) => (row.kind !== 'schedule' && PART_OF[row.kind] === part ? [rowPiece(row, index)] : []))

  const firstLook = form.rows.findIndex((row) => row.kind === 'look_for')
  const dayPieces = form.marked
    .filter((part) => part.reason === 'how_many_days')
    .map((part) => ({
      mark: question?.kind === 'days' ? ('ask' as const) : ('later' as const),
      body:
        question?.kind === 'days' ? (
          asked(
            ASK_DAYS,
            firstLook >= 0 ? (
              <button type="button" className={styles['choice']} onClick={() => open(firstLook)}>
                Change which tickets
              </button>
            ) : null,
          )
        ) : (
          <span className="muted">{`“${part.text}”: ${ASKED_NEXT.toLowerCase()}`}</span>
        ),
    }))

  const inputPiece = (agent: PlanAgent, input: PlanAgent['inputs'][number]): { readonly mark: Mark; readonly body: ReactNode } => {
    const fieldId = `${id}-value-${String(agent.index)}-${input.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
    const key = valueKey(agent.index, input.name)
    const value = valueOf(form, agent, input.name)
    const problem = valueProblem(input.kind, value)
    const said = shown || value !== '' ? problem : null
    const now = question?.kind === 'input' && question.agent === agent.index && question.input === input.name ? question : null
    if (problem !== null && now === null) return { mark: 'later', body: <span className="muted">{`${input.name}: ${ASKED_NEXT.toLowerCase()}`}</span> }
    const field = (
      <>
        <label className={styles['valueLabel']} htmlFor={fieldId}>
          {input.name}
        </label>
        <input
          id={fieldId}
          className={styles['value']}
          type="text"
          value={value}
          aria-invalid={said ? true : undefined}
          aria-describedby={`${fieldId}-help${said ? ` ${fieldId}-error` : ''}`}
          onChange={(event) => edit((before) => ({ ...before, typed: { ...before.typed, [key]: event.target.value } }))}
        />
        <span className={styles['help']} id={`${fieldId}-help`}>
          {input.what}
        </span>
        {said ? (
          <span className={styles['problem']} id={`${fieldId}-error`}>
            {said}
          </span>
        ) : null}
      </>
    )
    return { mark: now ? 'ask' : 'ok', body: now ? asked(now.words, field) : field }
  }

  const inputPieces = (part: PartKey) =>
    plan?.kind === 'agents' ? plan.agents.flatMap((agent) => agent.inputs.filter((input) => inputPart(input.kind) === part).map((input) => inputPiece(agent, input))) : []

  const parts: Part[] = [
    ...keyed('Watch', [...rowPieces('Watch'), ...dayPieces, ...inputPieces('Watch'), ...(youRun ? [{ mark: 'ok' as const, body: <span className={styles['pnote']}>You run {youRun}</span> }] : [])]),
    ...keyed('When', [whenPiece]),
    ...keyed('Then', [...rowPieces('Then'), ...inputPieces('Then'), ...(writes === false ? [] : [{ mark: 'ok' as const, body: <span className={styles['after']}>After a yes</span> }])]),
    ...crosses,
  ]
  const asks = left.choices.length > 0

  return (
    <div data-card={id}>
      <Card
        title={title}
        pill={<DraftPill label={creating ? 'Building' : 'Draft'} tone={creating ? 'new' : 'quiet'} />}
        status={
          <span id={`${id}-left`} role="status">
            {creating ? 'Starting…' : leftWords(left)}
          </span>
        }
        actions={
          creating ? undefined : (
            <>
              <Button onClick={neverMind}>Never mind</Button>
              <button type="button" id={`${id}-set-up`} className={buttonClassName(main)} aria-describedby={`${id}-left`} onClick={asks ? pointAtWhatIsLeft : pressSetUp}>
                {setUpWords(left)}
              </button>
            </>
          )
        }
      >
        <PartsList parts={parts} short />
        {plan?.kind === 'cannot' || plan?.kind === 'trouble' || planQuery.isError ? (
          <div className={styles['trouble']}>
            {plan?.kind === 'cannot' ? <p className={styles['problem']}>I can’t set this up. {plan.reason}</p> : null}
            {plan?.kind === 'trouble' || planQuery.isError ? (
              <>
                <p className={styles['problem']} role="alert">
                  {plan?.kind === 'trouble' ? plan.message : planQuery.isError ? words(planQuery.error) : ''}
                </p>
                <Button onClick={() => void planQuery.refetch()}>Try again</Button>
              </>
            ) : null}
          </div>
        ) : null}
        {plan?.kind === 'agents' && (plan.problems.length > 0 || plan.notIncluded.length > 0) ? (
          <ul className={styles['refused']}>
            {plan.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
            {plan.notIncluded.length > 0 ? <li>Left out, because no tool does it yet: {plan.notIncluded.join(', ')}.</li> : null}
          </ul>
        ) : null}
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
      </Card>
      {asking ? <DiscardDialog name={title} busy={deleteDraft.isPending} problem={discardProblem} onClose={() => setAsking(false)} onConfirm={confirmDiscard} /> : null}
    </div>
  )
}
