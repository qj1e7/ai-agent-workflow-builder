import { useEffect, useRef, useState, type FormEvent, type Ref, type RefObject } from 'react'
import { flushSync } from 'react-dom'
import { useErrorWords } from '../../api/context'
import { pressOnce, useLatch } from '../../api/latch'
import { useSaveSchedule, useTurnOffSchedule } from '../../api/queries'
import type { Day, ScheduleSaveIn, ScheduleView } from '../../api/types'
import { Button } from '../../ui/Button'
import { ConfirmLine } from '../../ui/ConfirmLine'
import { CHANGED_SINCE_OPENED, changedSinceOpened } from '../workflows/workflow'
import { checkClock, DAYS, dayOption, nextCheckWords, noScheduleWords, ONE_APPROVAL, scheduleOwnerWords, scheduleWords } from './software'
import styles from './Software.module.css'
import { teamPlace } from '../workflows/times'

export function ScheduleNote({ schedule, operator, paused }: { schedule: ScheduleView | null; operator: boolean; paused: boolean }) {
  if (schedule === null) return <p>{`${noScheduleWords({ operator, paused })} ${ONE_APPROVAL}`}</p>
  return (
    <>
      <p>
        <b>{scheduleWords(schedule)}</b> {ONE_APPROVAL} {nextCheckWords(schedule, paused)}
      </p>
      {schedule.held ? null : <p className="muted">{scheduleOwnerWords(schedule)}</p>}
    </>
  )
}

/** What a save needs from its mutation, so the Software page and the workflow page share one form. */
export interface SaveSchedule {
  readonly mutate: (body: ScheduleSaveIn, answers: { onSuccess: () => void; onError: (failure: unknown) => void }) => void
  readonly isPending: boolean
}

const ownerWarning = (work: string) => `Saving makes you the owner of this schedule. Its ${work} then count as your work, so you won’t be able to approve them.`

interface FormProps {
  readonly schedule: Pick<ScheduleView, 'day' | 'at'> | null
  /** The version the form opened on. A save carries it, so a teammate's later change is never saved over. */
  readonly version: number
  /** What the schedule starts, in the owner warning: "checks" or "runs". */
  readonly work: string
  readonly save: SaveSchedule
  readonly onDone: () => void
  /** A teammate changed it since the form opened, so nothing was saved and the form gives way to the schedule read again. */
  readonly onStale: () => void
}

export function ScheduleForm({ schedule, version, work, save, onDone, onStale }: FormProps) {
  const [day, setDay] = useState<Day>(schedule?.day ?? 'monday')
  const [at, setAt] = useState(schedule?.at ?? '09:00')
  const [opened] = useState(version)
  const [error, setError] = useState<string | undefined>()
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
    save.mutate(
      { day, at: clock.value, expected_version: opened },
      {
        onSuccess: onDone,
        onError: (failure) => (changedSinceOpened(failure) ? onStale() : setError(words(failure))),
      },
    )
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
        <label htmlFor="sched-at">Time, {teamPlace()}</label>
        <input id="sched-at" type="time" step={300} value={at} aria-invalid={error ? true : undefined} aria-describedby={error ? 'sched-error' : undefined} onChange={(event) => setAt(event.target.value)} />
      </div>
      <p className={styles['ownerNote']} id="sched-owner-note">
        {ownerWarning(work)}
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

interface EditorProps {
  readonly schedule: ScheduleView | null
  readonly version: number
  readonly onDone: () => void
  readonly onStale: () => void
}

export function ScheduleEditor({ schedule, version, onDone, onStale }: EditorProps) {
  return <ScheduleForm schedule={schedule} version={version} work="checks" save={useSaveSchedule()} onDone={onDone} onStale={onStale} />
}

export function useEditorThatRefocusesItsOpener() {
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

interface TurnOffProps {
  readonly confirming: boolean
  readonly busy: boolean
  readonly offButton: Ref<HTMLButtonElement>
  readonly onAsk: () => void
  readonly onKeep: () => void
  readonly onYes: () => void
}

export function TurnOffSchedule({ confirming, busy, offButton, onAsk, onKeep, onYes }: TurnOffProps) {
  if (!confirming) {
    return (
      <Button ref={offButton} data-place="schedule-off" loading={busy} onClick={onAsk}>
        Turn off schedule
      </Button>
    )
  }
  return (
    <ConfirmLine
      groupName="Turn off the schedule"
      question="Turn off the schedule? The watchlist won’t be checked until someone sets one again."
      keep="Keep it"
      yes="Yes, turn it off"
      busy={busy}
      onKeep={onKeep}
      onYes={onYes}
    />
  )
}

interface ScheduleProps {
  readonly schedule: ScheduleView | null
  /** The watchlist's version, as read. */
  readonly version: number
  readonly operator: boolean
  readonly paused: boolean
  /** Someone has the watchlist open in n8n, so nothing here can change now and the platform would refuse it. The page says who. */
  readonly held: boolean
}

export function Schedule({ schedule, version, operator, paused, held }: ScheduleProps) {
  const { editing, opener, open, close } = useEditorThatRefocusesItsOpener()
  const [refused, setRefused] = useState<string | null>(null)
  const stale = () => {
    setRefused(CHANGED_SINCE_OPENED)
    close()
  }
  const off = useTurnOffSchedule()
  const latch = useLatch()
  const offButton = useRef<HTMLButtonElement>(null)
  // The watchlist version the question was asked on, so any change to the watchlist closes it for good.
  const [askedOn, setAskedOn] = useState<number | null>(null)
  if (held && askedOn !== null) setAskedOn(null)
  const confirming = askedOn === version
  const closeQuestion = (focusOn: RefObject<HTMLButtonElement | null>) => {
    flushSync(() => setAskedOn(null))
    focusOn.current?.focus()
  }
  // A read can close the question while focus is in it, so focus goes back to Turn off schedule, or Set a schedule once it is gone.
  const wasConfirming = useRef(false)
  useEffect(() => {
    const fell = document.activeElement === null || document.activeElement === document.body
    if (wasConfirming.current && !confirming && fell) (offButton.current ?? opener.current)?.focus()
    wasConfirming.current = confirming
  }, [confirming, opener])
  const words = useErrorWords()
  return (
    <section className={styles['schedule']} aria-labelledby="schedule-heading">
      <h2 id="schedule-heading" className="visually-hidden">
        Schedule
      </h2>
      <div className={styles['scheduleText']}>
        <ScheduleNote schedule={schedule} operator={operator} paused={paused} />
      </div>
      {operator && held ? null : operator && !editing ? (
        <div className={styles['actions']}>
          {confirming ? null : (
            <Button
              ref={opener}
              data-place="schedule"
              onClick={() => {
                setRefused(null)
                open()
              }}
            >
              {schedule ? 'Change schedule' : 'Set a schedule'}
            </Button>
          )}
          {schedule ? (
            <TurnOffSchedule
              confirming={confirming}
              busy={off.isPending}
              offButton={offButton}
              onAsk={() => setAskedOn(version)}
              onKeep={() => closeQuestion(offButton)}
              onYes={() => pressOnce(latch, (outcome) => off.mutate(version, outcome), { onSuccess: () => closeQuestion(opener), onError: () => closeQuestion(offButton) })}
            />
          ) : null}
        </div>
      ) : null}
      {off.isError ? (
        <p className={styles['error']} role="alert">
          {words(off.error)}
        </p>
      ) : null}
      {refused ? (
        <p className={styles['error']} role="alert">
          {refused}
        </p>
      ) : null}
      {operator && editing && !held ? <ScheduleEditor schedule={schedule} version={version} onDone={close} onStale={stale} /> : null}
    </section>
  )
}
