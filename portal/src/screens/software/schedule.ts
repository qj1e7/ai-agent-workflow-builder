import type { Day, ScheduleIn, ScheduleView } from '../../api/types'

/** The days in the order the picker offers them, with the words the schedule line uses. */
export const DAYS: readonly { readonly day: Day; readonly label: string; readonly every: string }[] = [
  { day: 'every_day', label: 'Every day', every: 'every day' },
  { day: 'monday', label: 'Monday', every: 'every Monday' },
  { day: 'tuesday', label: 'Tuesday', every: 'every Tuesday' },
  { day: 'wednesday', label: 'Wednesday', every: 'every Wednesday' },
  { day: 'thursday', label: 'Thursday', every: 'every Thursday' },
  { day: 'friday', label: 'Friday', every: 'every Friday' },
  { day: 'saturday', label: 'Saturday', every: 'every Saturday' },
  { day: 'sunday', label: 'Sunday', every: 'every Sunday' },
]

export const DEFAULT_SCHEDULE: ScheduleIn = { day: 'monday', at: '09:00' }

const STEP_TIME = /^([01]\d|2[0-3]):[0-5][05]$/

/** "09:00" as people write it: "9:00". */
export function clockWords(at: string): string {
  return at.replace(/^0(\d)/, '$1')
}

function everyWords(day: Day): string {
  return DAYS.find((entry) => entry.day === day)?.every ?? day
}

/** "Checked every Monday at 9:00, set by Alice." */
export function scheduleWords(schedule: ScheduleView): string {
  return `Checked ${everyWords(schedule.day)} at ${clockWords(schedule.at)}, set by ${schedule.owner_name}.`
}

/** The schedule owner may never approve a scheduled check, so the line says so beside the schedule. */
export function ownerWords(schedule: ScheduleView, viewer: string | null): string {
  return viewer === schedule.owner
    ? 'Scheduled checks count as your work, so another Approver approves them.'
    : `Scheduled checks count as ${schedule.owner_name}'s work, so ${schedule.owner_name} can't approve them.`
}

const NEXT = new Intl.DateTimeFormat('en-SG', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Singapore',
})

/** "Next check Mon 30 Nov, 9:00", in the schedule's own time zone. */
export function nextWords(schedule: ScheduleView): string {
  const parts = Object.fromEntries(
    NEXT.formatToParts(new Date(schedule.next_at)).map((part) => [part.type, part.value]),
  )
  const hour = String(Number(parts['hour'] ?? '0') % 24)
  return `Next check ${parts['weekday'] ?? ''} ${parts['day'] ?? ''} ${parts['month'] ?? ''}, ${hour}:${parts['minute'] ?? '00'}`
}

export type ScheduleChecked =
  { readonly ok: true; readonly body: ScheduleIn } | { readonly ok: false; readonly problem: string }

export const TIME_PROBLEM = 'Pick a time on a 5-minute step, such as 9:00 or 9:05.'

export function checkSchedule(day: Day, at: string): ScheduleChecked {
  const time = at.trim().slice(0, 5)
  return STEP_TIME.test(time) ? { ok: true, body: { day, at: time } } : { ok: false, problem: TIME_PROBLEM }
}
