import { useEffect, useId, useRef, useState, type FormEvent, type RefObject } from 'react'
import { Link } from 'react-router'
import { useErrorWords } from '../../api/context'
import {
  useAddSoftware,
  useMe,
  useRemoveSoftware,
  useSaveSchedule,
  useTurnOffSchedule,
  useWatchlist,
} from '../../api/queries'
import type { Day, LastCheckView, ScheduleView, WatchlistView } from '../../api/types'
import { Button, ButtonLink } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import {
  IconAlert,
  IconCheck,
  IconClock,
  IconExternal,
  IconPlay,
  IconReplay,
  IconRing,
  IconTicket,
  IconWave,
  type Icon,
} from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import { Pill, type PillTone } from '../../ui/StatusPill'
import { useRunNow } from '../builder/useRunNow'
import { checkAdd, EMPTY_FIELDS, refusedAdd, type AddField, type AddFields, type FieldProblems } from './addForm'
import { checkSchedule, DAYS, DEFAULT_SCHEDULE, nextWords, ownerWords, scheduleWords } from './schedule'
import { softwareList, upToDateWords, type SoftwareRow } from './softwareList'
import styles from './SoftwarePage.module.css'

const TONE_ICON: Readonly<Record<PillTone, Icon>> = {
  failed: IconAlert,
  waiting: IconClock,
  working: IconTicket,
  neutral: IconRing,
  done: IconCheck,
}

const RUNNING = new Set<LastCheckView['state']>(['pending', 'working', 'proposed', 'acting'])

export function SoftwarePage() {
  const explain = useErrorWords()
  const watchlist = useWatchlist({ poll: true })
  const me = useMe().data
  const operator = me?.roles.includes('operator') ?? false
  const runNow = useRunNow()
  const view = watchlist.data ?? null
  const watched = (view?.software.length ?? 0) > 0
  const starting = view ? runNow.isStarting(view.use_case_id) : false
  const startProblem = view ? runNow.errorFor(view.use_case_id) : null

  return (
    <div className="page">
      <div className={styles['frame']}>
        <PageHeader
          title="Software"
          aside={
            operator && view && watched ? (
              <Button
                variant="primary"
                icon={IconPlay}
                loading={starting}
                onClick={() => runNow.start(view.use_case_id)}
              >
                Check now
              </Button>
            ) : null
          }
        >
          What needs a person comes first.
        </PageHeader>
        {startProblem ? <InlineMessage tone="error">{startProblem}</InlineMessage> : null}
        {watchlist.isSuccess ? (
          <Loaded view={view} operator={operator} viewer={me?.id ?? null} />
        ) : watchlist.isError ? (
          <div className={styles['problem']}>
            <InlineMessage tone="error">We could not load the watchlist. {explain(watchlist.error)}</InlineMessage>
            <Button icon={IconReplay} loading={watchlist.isFetching} onClick={() => void watchlist.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <div className={`panel ${styles['padded']}`}>
            <Skeleton lines={4} label="Loading the watchlist" />
          </div>
        )}
      </div>
    </div>
  )
}

interface LoadedProps {
  view: WatchlistView | null
  operator: boolean
  viewer: string | null
}

function Loaded({ view, operator, viewer }: LoadedProps) {
  const list = softwareList(view)
  const heading = useRef<HTMLHeadingElement>(null)
  const [removed, setRemoved] = useState<string | null>(null)
  const empty = list.attention.length === 0 && list.upToDate.length === 0

  function onRemoved(name: string) {
    setRemoved(name)
    heading.current?.focus()
  }

  return (
    <div className={styles['sections']}>
      {empty ? (
        <section className={styles['empty']} aria-labelledby="software-empty">
          <h2 id="software-empty">No software yet</h2>
          <p className="muted">
            {operator
              ? 'Add the software the team runs. Each check looks for new releases and drafts an upgrade ticket for an Approver.'
              : 'An Operator adds the software the team runs. Each check looks for new releases and drafts an upgrade ticket for an Approver.'}
          </p>
        </section>
      ) : (
        <>
          {view ? <Schedule view={view} operator={operator} viewer={viewer} /> : null}
          {view?.last_check && RUNNING.has(view.last_check.state) ? <Running check={view.last_check} /> : null}
          <section aria-labelledby="attention-heading" className={styles['list']}>
            <h2 id="attention-heading" ref={heading} tabIndex={-1}>
              Needs a person
            </h2>
            {removed ? <InlineMessage tone="success">Removed {removed}.</InlineMessage> : null}
            {list.attention.length > 0 ? (
              <ul className={`panel ${styles['rows']}`}>
                {list.attention.map((row) => (
                  <li key={row.id}>
                    <Row row={row} operator={operator} onRemoved={onRemoved} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles['calm']}>
                <IconCheck size={20} />
                Nothing needs a person.
              </p>
            )}
            {list.upToDate.length > 0 ? (
              <details className={styles['fold']}>
                <summary className="disclosure">{upToDateWords(list.upToDate.length)}</summary>
                <ul className={`panel ${styles['rows']}`}>
                  {list.upToDate.map((row) => (
                    <li key={row.id}>
                      <Row row={row} operator={operator} onRemoved={onRemoved} />
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </section>
        </>
      )}
      {operator ? <AddForm first={empty} /> : <p className="muted">Operators add and remove software.</p>}
    </div>
  )
}

function Running({ check }: { check: LastCheckView }) {
  return (
    <p className={styles['running']} role="status">
      <IconWave size={18} />
      <span>A check is running.</span>
      <Link to={`/runs/${check.run_id}`}>Watch the check</Link>
    </p>
  )
}

interface RowProps {
  row: SoftwareRow
  operator: boolean
  onRemoved: (name: string) => void
}

function Row({ row, operator, onRemoved }: RowProps) {
  const explain = useErrorWords()
  const remove = useRemoveSoftware()
  const [confirming, setConfirming] = useState(false)
  const keep = useRef<HTMLButtonElement>(null)
  const ask = useRef<HTMLButtonElement>(null)
  const askedBefore = useRef(false)

  useEffect(() => {
    if (confirming) keep.current?.focus()
    else if (askedBefore.current) ask.current?.focus()
    askedBefore.current = confirming
  }, [confirming])

  return (
    <article className={cx(styles['row'], row.problem && styles['rowWithWhy'])} aria-labelledby={`${row.id}-name`}>
      <div className={styles['what']}>
        <h3 id={`${row.id}-name`}>{row.name}</h3>
        <a className={styles['source']} href={row.source.url} target="_blank" rel="noopener noreferrer">
          {row.source.ref}
          <IconExternal size={14} />
          <span className="visually-hidden"> (GitHub releases, opens in a new tab)</span>
        </a>
      </div>
      <dl className={styles['versions']}>
        <div>
          <dt>Ours</dt>
          <dd>
            {row.ours ? <span className={styles['version']}>{row.ours}</span> : null}
            <span className={styles['from']}>{row.oursFrom}</span>
          </dd>
        </div>
        {row.newest ? (
          <div>
            <dt>Newest</dt>
            <dd>
              <span className={styles['version']}>{row.newest}</span>
            </dd>
          </div>
        ) : null}
      </dl>
      <div className={styles['state']}>
        <Pill tone={row.tone} icon={TONE_ICON[row.tone]}>
          {row.label}
        </Pill>
      </div>
      {row.problem ? <p className={styles['why']}>{row.problem}</p> : null}
      <div className={styles['acts']}>
        {row.next?.is === 'approval' ? <ButtonLink to={row.next.to}>Open the approval</ButtonLink> : null}
        {row.next?.is === 'ticket' ? (
          <Link to="/jira" className={styles['ticket']}>
            <IconTicket size={16} />
            {row.next.key}
            <span className="visually-hidden">, open in Jira</span>
          </Link>
        ) : null}
        {operator && !confirming ? (
          <button ref={ask} type="button" className={styles['remove']} onClick={() => setConfirming(true)}>
            Remove<span className="visually-hidden"> {row.name}</span>
          </button>
        ) : null}
      </div>
      {confirming ? (
        <div className={styles['confirm']} role="group" aria-label={`Remove ${row.name}?`}>
          <span className={styles['ask']}>Remove {row.name} from the list?</span>
          <Button
            variant="danger-outline"
            loading={remove.isPending}
            onClick={() => remove.mutate(row.id, { onSuccess: () => onRemoved(row.name) })}
          >
            Remove
          </Button>
          <Button ref={keep} disabled={remove.isPending} onClick={() => setConfirming(false)}>
            Keep
          </Button>
        </div>
      ) : null}
      {remove.isError ? (
        <div className={styles['rowProblem']}>
          <InlineMessage tone="error">{explain(remove.error)}</InlineMessage>
        </div>
      ) : null}
    </article>
  )
}

interface ScheduleProps {
  view: WatchlistView
  operator: boolean
  viewer: string | null
}

function Schedule({ view, operator, viewer }: ScheduleProps) {
  const [editing, setEditing] = useState(false)
  const change = useRef<HTMLButtonElement>(null)
  const wasEditing = useRef(false)
  const schedule = view.schedule ?? null

  useEffect(() => {
    if (!editing && wasEditing.current) change.current?.focus()
    wasEditing.current = editing
  }, [editing])

  return (
    <section className={styles['schedule']} aria-labelledby="schedule-heading">
      <h2 id="schedule-heading" className="visually-hidden">
        Schedule
      </h2>
      <IconClock size={20} />
      <div className={styles['scheduleWords']}>
        {schedule ? (
          <>
            <p className={styles['when']}>
              {scheduleWords(schedule)} <span className={styles['next']}>{nextWords(schedule)}.</span>
            </p>
            <p className={styles['owner']}>{ownerWords(schedule, viewer)}</p>
          </>
        ) : (
          <p className={styles['when']}>
            Not checked on a schedule. A check starts only when an Operator presses Check now.
          </p>
        )}
      </div>
      {operator && !editing ? (
        <Button ref={change} onClick={() => setEditing(true)}>
          {schedule ? 'Change' : 'Set a schedule'}
        </Button>
      ) : null}
      {operator && editing ? <ScheduleForm schedule={schedule} onDone={() => setEditing(false)} /> : null}
    </section>
  )
}

function ScheduleForm({ schedule, onDone }: { schedule: ScheduleView | null; onDone: () => void }) {
  const explain = useErrorWords()
  const id = useId()
  const save = useSaveSchedule()
  const turnOff = useTurnOffSchedule()
  const [day, setDay] = useState<Day>(schedule?.day ?? DEFAULT_SCHEDULE.day)
  const [at, setAt] = useState(schedule?.at ?? DEFAULT_SCHEDULE.at)
  const [problem, setProblem] = useState<string | null>(null)
  const first = useRef<HTMLSelectElement>(null)
  const busy = save.isPending || turnOff.isPending

  useEffect(() => first.current?.focus(), [])

  function onSave(event: FormEvent) {
    event.preventDefault()
    const checked = checkSchedule(day, at)
    if (!checked.ok) {
      setProblem(checked.problem)
      return
    }
    setProblem(null)
    save.mutate(checked.body, { onSuccess: onDone })
  }

  const error = save.error ?? turnOff.error
  return (
    <form className={styles['scheduleForm']} onSubmit={onSave} noValidate aria-label="Change the schedule">
      <div className={styles['scheduleFields']}>
        <div className={styles['field']}>
          <label htmlFor={`${id}-day`}>Day</label>
          <select
            ref={first}
            id={`${id}-day`}
            className={styles['input']}
            value={day}
            disabled={busy}
            onChange={(event) => setDay(event.target.value as Day)}
          >
            {DAYS.map((entry) => (
              <option key={entry.day} value={entry.day}>
                {entry.label}
              </option>
            ))}
          </select>
        </div>
        <div className={styles['field']}>
          <label htmlFor={`${id}-at`}>Time in Singapore</label>
          <input
            id={`${id}-at`}
            className={styles['input']}
            type="time"
            step={300}
            value={at}
            disabled={busy}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? `${id}-at-problem` : undefined}
            onChange={(event) => {
              setAt(event.target.value)
              setProblem(null)
            }}
          />
        </div>
      </div>
      {problem ? (
        <InlineMessage tone="error" id={`${id}-at-problem`}>
          {problem}
        </InlineMessage>
      ) : null}
      <p className={styles['help']}>Saving makes you the schedule owner, so you can't approve scheduled checks.</p>
      <div className={styles['formActs']}>
        <Button type="submit" variant="primary" loading={save.isPending} disabled={turnOff.isPending}>
          Save
        </Button>
        {schedule ? (
          <Button
            variant="danger-outline"
            loading={turnOff.isPending}
            disabled={save.isPending}
            onClick={() => turnOff.mutate(undefined, { onSuccess: onDone })}
          >
            Turn off
          </Button>
        ) : null}
        <button type="button" className={styles['link']} disabled={busy} onClick={onDone}>
          Cancel
        </button>
      </div>
      {error ? <InlineMessage tone="error">{explain(error)}</InlineMessage> : null}
    </form>
  )
}

function AddForm({ first }: { first: boolean }) {
  const explain = useErrorWords()
  const id = useId()
  const add = useAddSoftware()
  const [fields, setFields] = useState<AddFields>(EMPTY_FIELDS)
  const [problems, setProblems] = useState<FieldProblems>({})
  const [formProblem, setFormProblem] = useState<string | null>(null)
  const [added, setAdded] = useState<string | null>(null)
  const [explained, setExplained] = useState(false)
  const inputs: Record<AddField, RefObject<HTMLInputElement | null>> = {
    name: useRef<HTMLInputElement>(null),
    repo: useRef<HTMLInputElement>(null),
    ourVersion: useRef<HTMLInputElement>(null),
  }

  function edit(field: AddField, value: string) {
    setFields((current) => ({ ...current, [field]: value }))
    setProblems((current) => ({ ...current, [field]: undefined }))
    setFormProblem(null)
    setAdded(null)
    add.reset()
  }

  function focusFirst(found: FieldProblems) {
    const field = (['name', 'repo', 'ourVersion'] as const).find((candidate) => found[candidate])
    if (field) inputs[field].current?.focus()
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const checked = checkAdd(fields)
    if (!checked.ok) {
      setProblems(checked.problems)
      focusFirst(checked.problems)
      return
    }
    add.mutate(checked.body, {
      onSuccess: () => {
        setFields(EMPTY_FIELDS)
        setProblems({})
        setAdded(checked.body.name)
        inputs.name.current?.focus()
      },
      onError: (error) => {
        const refused = refusedAdd(error, checked.body)
        setExplained(refused !== null)
        if (!refused) return
        setProblems(refused.fields)
        setFormProblem(refused.form)
        focusFirst(refused.fields)
      },
    })
  }

  function field(name: AddField, label: string, options: { help?: string; placeholder?: string; optional?: boolean }) {
    const problem = problems[name]
    const helpId = `${id}-${name}-help`
    const problemId = `${id}-${name}-problem`
    const describedBy =
      [options.help ? helpId : null, problem ? problemId : null].filter(Boolean).join(' ') || undefined
    return (
      <div className={styles['field']}>
        <label htmlFor={`${id}-${name}`}>
          {label}
          {options.optional ? <span className={styles['optional']}> (optional)</span> : null}
        </label>
        <input
          ref={inputs[name]}
          id={`${id}-${name}`}
          className={styles['input']}
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder={options.placeholder}
          value={fields[name]}
          disabled={add.isPending}
          aria-invalid={problem ? true : undefined}
          aria-describedby={describedBy}
          onChange={(event) => edit(name, event.target.value)}
        />
        {options.help ? (
          <p id={helpId} className={styles['help']}>
            {options.help}
          </p>
        ) : null}
        {problem ? (
          <InlineMessage tone="error" id={problemId}>
            {problem}
          </InlineMessage>
        ) : null}
      </div>
    )
  }

  return (
    <section className={cx('panel', styles['add'])} aria-labelledby="add-heading">
      <h2 id="add-heading">{first ? 'Add the first software' : 'Add software'}</h2>
      <form className={styles['addForm']} onSubmit={onSubmit} noValidate>
        <div className={styles['addFields']}>
          {field('name', 'Name', { placeholder: 'LangGraph' })}
          {field('repo', 'GitHub repository', { placeholder: 'owner/name', help: 'A GitHub link works too.' })}
          {field('ourVersion', 'Our version', {
            optional: true,
            placeholder: '1.2.14',
            help: 'Left empty, the first check takes the newest.',
          })}
        </div>
        <div className={styles['formActs']}>
          <Button type="submit" variant="primary" loading={add.isPending}>
            Add
          </Button>
        </div>
        {formProblem ? <InlineMessage tone="error">{formProblem}</InlineMessage> : null}
        {add.isError && !explained ? <InlineMessage tone="error">{explain(add.error)}</InlineMessage> : null}
        {added ? <InlineMessage tone="success">Added {added}. The next check reads it.</InlineMessage> : null}
      </form>
    </section>
  )
}
