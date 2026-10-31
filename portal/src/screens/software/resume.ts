import { pressOnce, type Latch, type Outcome } from '../../api/latch'

export type SchedulePlace = 'resume' | 'schedule' | 'schedule-off'
export const SCHEDULE_PLACES_IN_PAGE_ORDER: readonly SchedulePlace[] = ['resume', 'schedule', 'schedule-off']

export function schedulePlaces({ paused, scheduled }: { readonly paused: boolean; readonly scheduled: boolean }): SchedulePlace[] {
  return SCHEDULE_PLACES_IN_PAGE_ORDER.filter((place) => (place === 'resume' ? paused : place === 'schedule-off' ? scheduled : true))
}

/** Resuming answers with a view the page does not read, so success takes no value. */
export type ResumeOutcome = Omit<Outcome, 'onSuccess'> & { onSuccess?: () => void }

interface ResumeAnswers {
  readonly resumed: () => void
  readonly refused: (problem: string, error: unknown) => void
}

export function pressResume(latch: Latch, send: (outcome: ResumeOutcome) => void, { resumed, refused }: ResumeAnswers, words: (error: unknown) => string): void {
  pressOnce<void>(latch, send, { onSuccess: resumed, onError: (error) => refused(`Could not resume the watchlist. ${words(error)}`, error) })
}
