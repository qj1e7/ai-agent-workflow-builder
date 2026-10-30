import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useSaveSchedule, useTurnOffSchedule } from '../../api/queries'
import type { Day, ScheduleView } from '../../api/types'
import { useMoveWorkflow, useRereadWorkflow } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { useFocusAfterReread } from '../../ui/focus'
import { IconPlay } from '../../ui/icons'
import { meansOutOfDate } from '../workflows/workflow'
import { pressResume, SCHEDULE_PLACES_IN_PAGE_ORDER, schedulePlaces, type SchedulePlace } from './resume'
import { checkClock, DAYS, dayOption, nextCheckWords, noScheduleWords, scheduleOwnerWords, scheduleWords } from './software'
import styles from './Software.module.css'

export function ScheduleNote({ schedule, operator, paused }: { schedule: ScheduleView | null; operator: boolean; paused: boolean }) {
  if (schedule === null) return <p>{noScheduleWords({ operator, paused })}</p>
  return (
    <>
      <p>
        <b>{scheduleWords(schedule)}</b> {nextCheckWords(schedule, paused)}
      </p>
      {schedule.held ? null : <p className="muted">{scheduleOwnerWords(schedule)}</p>}
    </>
  )
}

const OWNER_WARNING = 'Saving makes you the owner of this schedule. Its checks then count as your work, so you won’t be able to approve them.'

export function ScheduleEditor({ schedule, onDone }: { schedule: ScheduleView | null; onDone: () => void }) {
  const [day, setDay] = useState<Day>(schedule?.day ?? 'monday')
  const [at, setAt] = useState(schedule?.at ?? '09:00')
  const [error, setError] = useState<string | undefined>()
  const save = useSaveSchedule()
  const words = useErrorWords()
  const first = useRef<HTMLSelectElement>(null)
  useEffect(() => first.current?.focus(), [])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (save.isPending) return
    const clock = checkClock(at)
    if (!clock.ok) {
      setError(clock.words)
      return
    }
    setError(undefined)
    save.mutate({ day, at: clock.value }, { onSuccess: onDone, onError: (failure) => setError(words(failure)) })
  }

  return (
    <form className={styles['scheduleForm']} onSubmit={submit} noValidate aria-label="Change schedule">
      <div className={styles['field']}>
        <label htmlFor="sched-day">Day</label>
        <select id="sched-day" ref={first} value={day} onChange={(event) => setDay(event.target.value as Day)}>
          {DAYS.map((option) => (
            <option key={option} value={option}>
              {dayOption[option]}
            </option>
          ))}
        </select>
      </div>
      <div className={styles['field']}>
        <label htmlFor="sched-at">Time, Singapore</label>
        <input id="sched-at" type="time" step={300} value={at} aria-invalid={error ? true : undefined} aria-describedby={error ? 'sched-error' : undefined} onChange={(event) => setAt(event.target.value)} />
      </div>
      <p className={styles['ownerNote']} id="sched-owner-note">
        {OWNER_WARNING}
      </p>
      <div className={styles['actions']}>
        <Button type="submit" variant="primary" loading={save.isPending} aria-describedby="sched-owner-note">
          Save schedule
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
      {error ? (
        <p className={styles['error']} id="sched-error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  )
}

function useEditorThatRefocusesItsOpener() {
  const [editing, setEditing] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)
  const closing = useRef(false)
  useEffect(() => {
    if (editing || !closing.current) return
    closing.current = false
    opener.current?.focus()
  }, [editing])
  const open = () => setEditing(true)
  const close = () => {
    closing.current = true
    setEditing(false)
  }
  return { editing, opener, open, close }
}

function useResume(useCaseId: string, shown: readonly SchedulePlace[], answeredAt: number, onResumed: () => void) {
  const move = useMoveWorkflow()
  const reread = useRereadWorkflow()
  const latch = useLatch()
  const words = useErrorWords()
  const [problem, setProblem] = useState<string | null>(null)
  const refocus = useFocusAfterReread(SCHEDULE_PLACES_IN_PAGE_ORDER, shown, answeredAt)
  const press = () =>
    pressResume(
      latch,
      (outcome) => move.mutate({ move: 'resume', useCaseId }, outcome),
      {
        resumed: () => {
          setProblem(null)
          refocus('resume')
          onResumed()
        },
        refused: (said, error) => {
          setProblem(said)
          if (!meansOutOfDate(error)) return
          refocus('resume')
          reread(useCaseId)
        },
      },
      words,
    )
  return { press, pending: move.isPending, problem }
}

interface ScheduleProps {
  readonly schedule: ScheduleView | null
  readonly operator: boolean
  readonly paused: boolean
  readonly useCaseId: string
  readonly answeredAt: number
  readonly onResumed: () => void
}

export function Schedule({ schedule, operator, paused, useCaseId, answeredAt, onResumed }: ScheduleProps) {
  const { editing, opener, open, close } = useEditorThatRefocusesItsOpener()
  const off = useTurnOffSchedule()
  const resume = useResume(useCaseId, schedulePlaces({ paused, scheduled: schedule !== null }), answeredAt, onResumed)
  const words = useErrorWords()
  return (
    <section className={styles['schedule']} aria-labelledby="schedule-heading">
      <h2 id="schedule-heading" className="visually-hidden">
        Schedule
      </h2>
      <div className={styles['scheduleText']}>
        <ScheduleNote schedule={schedule} operator={operator} paused={paused} />
      </div>
      {operator && !editing ? (
        <div className={styles['actions']}>
          {paused ? (
            <Button data-place="resume" icon={IconPlay} loading={resume.pending} onClick={resume.press}>
              Resume
            </Button>
          ) : null}
          <Button ref={opener} data-place="schedule" onClick={open}>
            {schedule ? 'Change schedule' : 'Set a schedule'}
          </Button>
          {schedule ? (
            <Button data-place="schedule-off" loading={off.isPending} onClick={() => off.mutate(undefined, { onSuccess: () => opener.current?.focus() })}>
              Turn off schedule
            </Button>
          ) : null}
        </div>
      ) : null}
      {resume.problem ? (
        <p className={styles['error']} role="alert">
          {resume.problem}
        </p>
      ) : null}
      {off.isError ? (
        <p className={styles['error']} role="alert">
          {words(off.error)}
        </p>
      ) : null}
      {operator && editing ? <ScheduleEditor schedule={schedule} onDone={close} /> : null}
    </section>
  )
}
