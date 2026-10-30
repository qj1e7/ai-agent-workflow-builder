import type { Latch } from '../../api/latch'

/** The schedule controls in page order. Resume comes first, so the schedule button takes its place once it goes. */
export type SchedulePlace = 'resume' | 'schedule' | 'schedule-off'
export const SCHEDULE_PLACES: readonly SchedulePlace[] = ['resume', 'schedule', 'schedule-off']

export function schedulePlaces({ paused, scheduled }: { readonly paused: boolean; readonly scheduled: boolean }): SchedulePlace[] {
  return SCHEDULE_PLACES.filter((place) => (place === 'resume' ? paused : place === 'schedule-off' ? scheduled : true))
}

export interface ResumeOutcome {
  onSuccess?: () => void
  onError?: (error: unknown) => void
  onSettled?: () => void
}

interface ResumeAnswers {
  readonly resumed: () => void
  readonly refused: (problem: string, error: unknown) => void
}

export function pressResume(latch: Latch, send: (outcome: ResumeOutcome) => void, { resumed, refused }: ResumeAnswers, words: (error: unknown) => string): void {
  latch.run((settled) => send({ onSuccess: resumed, onError: (error) => refused(`Could not resume the watchlist. ${words(error)}`, error), onSettled: settled }))
}
