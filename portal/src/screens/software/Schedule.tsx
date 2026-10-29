import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useErrorWords } from '../../api/context'
import { useSaveSchedule, useTurnOffSchedule } from '../../api/queries'
import type { Day, ScheduleView } from '../../api/types'
import { Button } from '../../ui/Button'
import { checkClock, DAYS, dayOption, scheduleOwnerWords, scheduleWords, singaporeTime } from './software'
import styles from './Software.module.css'

export function ScheduleNote({ schedule }: { schedule: ScheduleView | null }) {
  if (schedule === null) return <p>No schedule yet. Checks start only when an Operator presses Check now.</p>
  return (
    <>
      <p>
        <b>{scheduleWords(schedule)}</b> Next check {singaporeTime(schedule.next_at)}, Singapore time.
      </p>
      <p className="muted">{scheduleOwnerWords(schedule)}</p>
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

/** Opening the editor hides the button that opened it, so closing the editor puts focus back on that button. */
export function Schedule({ schedule, operator }: { schedule: ScheduleView | null; operator: boolean }) {
  const [editing, setEditing] = useState(false)
  const off = useTurnOffSchedule()
  const words = useErrorWords()
  const opener = useRef<HTMLButtonElement>(null)
  const returning = useRef(false)
  useEffect(() => {
    if (editing || !returning.current) return
    returning.current = false
    opener.current?.focus()
  }, [editing])
  function close() {
    returning.current = true
    setEditing(false)
  }
  return (
    <section className={styles['schedule']} aria-labelledby="schedule-heading">
      <h2 id="schedule-heading" className="visually-hidden">
        Schedule
      </h2>
      <div className={styles['scheduleText']}>
        <ScheduleNote schedule={schedule} />
      </div>
      {operator && !editing ? (
        <div className={styles['actions']}>
          <Button ref={opener} onClick={() => setEditing(true)}>
            {schedule ? 'Change schedule' : 'Set a schedule'}
          </Button>
          {schedule ? (
            <Button loading={off.isPending} onClick={() => off.mutate(undefined, { onSuccess: () => opener.current?.focus() })}>
              Turn off schedule
            </Button>
          ) : null}
        </div>
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
