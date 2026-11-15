import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import type { Day, ScheduleSaveIn, UseCaseView } from '../../api/types'
import { useRereadWorkflow, useSaveWorkflowSchedule } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { checkClock, DAYS, everyWords } from '../software/software'
import { useEditorThatRefocusesItsOpener } from '../software/Schedule'
import { useChanges } from './Status'
import { CHANGED_SINCE_OPENED, heldNote, nextRunWords, OWNER_WARNING, scheduleSaver, whenWords } from './workflow'
import styles from './Workflows.module.css'
import { teamPlace, teamTime } from './times'

const capital = (words: string): string => `${words.charAt(0).toUpperCase()}${words.slice(1)}`

interface EditorProps {
  readonly schedule: Pick<NonNullable<UseCaseView['schedule']>, 'day' | 'at'> | null
  /** The version the editor opened on. A save carries it, so a teammate's later change is never saved over. */
  readonly version: number
  readonly isPending: boolean
  readonly save: (body: ScheduleSaveIn, form: { onSuccess: () => void; onError: (failure: unknown) => void }) => void
  readonly onDone: () => void
}

/** The sketch's inline editor: a day, a time, Save and Cancel. The time is any 5-minute step, since the platform takes any, and a time is never guessed. */
export function WhenEditor({ schedule, version, isPending, save, onDone }: EditorProps) {
  const [day, setDay] = useState<Day>(schedule?.day ?? 'every_day')
  const [at, setAt] = useState(schedule?.at ?? '')
  const [opened] = useState(version)
  const [error, setError] = useState<string | undefined>()
  const words = useErrorWords()
  const first = useRef<HTMLSelectElement>(null)
  const ids = useId()
  useEffect(() => first.current?.focus(), [])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isPending) return
    const clock = checkClock(at)
    if (!clock.ok) {
      setError(clock.words)
      return
    }
    setError(undefined)
    save({ day, at: clock.value, expected_version: opened }, { onSuccess: onDone, onError: (failure) => setError(words(failure)) })
  }

  return (
    <form className={styles['whenForm']} onSubmit={submit} noValidate aria-label="Change when it runs">
      <div className={styles['whenFields']}>
        <label htmlFor={`${ids}-day`} className="visually-hidden">
          Day
        </label>
        <select id={`${ids}-day`} ref={first} value={day} onChange={(event) => setDay(event.target.value as Day)}>
          {DAYS.map((option) => (
            <option key={option} value={option}>
              {capital(everyWords(option))}
            </option>
          ))}
        </select>
        <label htmlFor={`${ids}-at`} className="visually-hidden">
          Time, {teamPlace()}
        </label>
        <input id={`${ids}-at`} type="time" step={300} value={at} aria-invalid={error ? true : undefined} aria-describedby={error ? `${ids}-error` : undefined} onChange={(event) => setAt(event.target.value)} />
        <Button type="submit" variant="primary" loading={isPending} aria-describedby={`${ids}-owner`}>
          Save
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
      <p className={styles['small']} id={`${ids}-owner`}>
        {OWNER_WARNING} Times are {teamTime()}.
      </p>
      {error ? (
        <p className={styles['problem']} id={`${ids}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  )
}

interface WhenProps {
  readonly useCase: UseCaseView
  readonly now: Date
  /** Only an Operator changes a schedule, and not the Software watchlist's, which is changed on its page. */
  readonly mayChange: boolean
  readonly onSaved: (words: string) => void
}

/**
 * When, as the sketch draws it: the schedule in words, Change beside it, and the editor in its place while it is open. A save from a
 * version no longer in use closes the editor, so the schedule read again shows in its place, with the platform's words under it.
 */
export function When({ useCase, now, mayChange, onSaved }: WhenProps) {
  const id = useCase.use_case_id
  const headingId = useId()
  const save = useSaveWorkflowSchedule(id)
  const reread = useRereadWorkflow()
  const { editing, opener, open, close } = useEditorThatRefocusesItsOpener()
  const [refused, setRefused] = useState<string | null>(null)
  const { words, small } = whenWords(useCase)
  const next = heldNote(useCase) ?? `Next run: ${nextRunWords(useCase, now)}`
  const changes = useChanges(next)
  const stale = () => {
    setRefused(CHANGED_SINCE_OPENED)
    close()
  }
  const saver = scheduleSaver((body, answers) => save.mutate(body, answers), { useCaseId: id, now, say: onSaved, refocus: () => undefined, reread, stale })
  return (
    <section className={styles['section']} aria-labelledby={headingId}>
      <h2 id={headingId}>When</h2>
      {editing && mayChange ? (
        <WhenEditor schedule={useCase.schedule} version={useCase.version} isPending={save.isPending} save={saver} onDone={close} />
      ) : (
        <div className={styles['whenRow']}>
          <span>{words}</span>
          {mayChange ? (
            <Button
              ref={opener}
              data-place="schedule"
              onClick={() => {
                setRefused(null)
                open()
              }}
            >
              {useCase.schedule ? 'Change' : 'Set'}
              <span className="visually-hidden"> when it runs</span>
            </Button>
          ) : null}
        </div>
      )}
      <p className={styles['small']}>
        {small}
        {useCase.schedule ? ` Set by ${useCase.schedule.owner_name}.` : ''}{' '}
        <span key={changes} className={changes > 0 ? styles['changed'] : undefined}>
          {next}
        </span>
      </p>
      {refused ? (
        <p className={styles['problem']} role="alert">
          {refused}
        </p>
      ) : null}
    </section>
  )
}
