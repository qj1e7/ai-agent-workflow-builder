import { Button } from '../../ui/Button'
import { IconInfo } from '../../ui/icons'
import { readWhen, type Often, type Weekday, type When, type WhenField } from './draft'
import styles from './NewWorkflow.module.css'

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

export const whenFieldId = (field: WhenField) => `when-${field}`

function described(field: WhenField, problem: string | undefined, help?: boolean): string | undefined {
  const ids = [help ? `${whenFieldId(field)}-help` : '', problem ? `${whenFieldId(field)}-error` : ''].filter(Boolean)
  return ids.length > 0 ? ids.join(' ') : undefined
}

function Problem({ field, problem }: { field: WhenField; problem: string | undefined }) {
  return problem ? (
    <span className={styles['error']} id={`${whenFieldId(field)}-error`}>
      {problem}
    </span>
  ) : null
}

function FilledFrom({ asked, when }: { asked: string; when: When }) {
  if (asked === '') return <p className={styles['note']}>Your request didn’t say when, so nothing is filled in.</p>
  const read = readWhen(asked)
  const changed = (read.often !== '' && read.often !== when.often) || (read.day !== '' && read.day !== when.day) || (read.at !== '' && read.at !== when.at)
  return (
    <p className={styles['note']}>
      {changed ? (
        <>
          <IconInfo size={16} /> Your request said “{asked}”. That’s fine if you changed your mind.
        </>
      ) : (
        `Filled in from your words: ${asked}.`
      )}
    </p>
  )
}

interface StepWhenProps {
  readonly when: When
  readonly asked: string
  readonly problems: Partial<Record<WhenField, string>>
  readonly onWhen: (when: When) => void
  readonly onBack: () => void
  readonly onNext: () => void
}

export function StepWhen({ when, asked, problems, onWhen, onBack, onNext }: StepWhenProps) {
  return (
    <>
      <section className={styles['panel']} aria-labelledby="when-h">
        <h2 id="when-h">When should it run?</h2>
        <div className={styles['schedule']}>
          <div className={styles['field']}>
            <label htmlFor={whenFieldId('often')}>How often</label>
            <select
              id={whenFieldId('often')}
              value={when.often}
              aria-invalid={problems.often ? true : undefined}
              aria-describedby={described('often', problems.often)}
              onChange={(event) => onWhen({ ...when, often: event.target.value as Often })}
            >
              <option value="">Choose…</option>
              {OFTEN.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <Problem field="often" problem={problems.often} />
          </div>
          {when.often === 'week' ? (
            <div className={styles['field']}>
              <label htmlFor={whenFieldId('day')}>Day</label>
              <select
                id={whenFieldId('day')}
                value={when.day}
                aria-invalid={problems.day ? true : undefined}
                aria-describedby={described('day', problems.day)}
                onChange={(event) => onWhen({ ...when, day: event.target.value as Weekday | '' })}
              >
                <option value="">Choose…</option>
                {DAYS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <Problem field="day" problem={problems.day} />
            </div>
          ) : null}
          <div className={styles['field']}>
            <label htmlFor={whenFieldId('at')}>Time</label>
            <input
              id={whenFieldId('at')}
              type="time"
              step={300}
              value={when.at}
              aria-invalid={problems.at ? true : undefined}
              aria-describedby={described('at', problems.at, true)}
              onChange={(event) => onWhen({ ...when, at: event.target.value })}
            />
            <span className={styles['help']} id={`${whenFieldId('at')}-help`}>
              Singapore time (SGT)
            </span>
            <Problem field="at" problem={problems.at} />
          </div>
        </div>
        <FilledFrom asked={asked} when={when} />
      </section>
      <div className={styles['foot']}>
        <Button onClick={onBack}>Back</Button>
        <Button variant="primary" onClick={onNext}>
          Next
        </Button>
      </div>
    </>
  )
}
