import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { errorWords } from '../../api/errors'
import { createLatch } from '../../api/latch'
import { placeAfterRedraw } from '../../ui/focus'
import { pressResume, SCHEDULE_PLACES_IN_PAGE_ORDER, schedulePlaces, type ResumeOutcome } from './resume'

const words = (error: unknown) => errorWords(error, 'dev')

function harness() {
  const outcomes: ResumeOutcome[] = []
  const said: string[] = []
  const press = (latch = createLatch()) => {
    pressResume(latch, (outcome) => outcomes.push(outcome), { resumed: () => said.push('resumed'), refused: (problem) => said.push(problem) }, words)
    return latch
  }
  return { outcomes, said, press }
}

describe('Resume on the Software page', () => {
  it('sends one resume for quick presses, until the platform answers', () => {
    const h = harness()
    const latch = h.press()
    pressResume(latch, (outcome) => h.outcomes.push(outcome), { resumed: () => undefined, refused: () => undefined }, words)
    expect(h.outcomes).toHaveLength(1)
    h.outcomes[0]?.onSettled?.()
    h.press(latch)
    expect(h.outcomes).toHaveLength(2)
  })

  it('says it resumed, or why it could not', () => {
    const h = harness()
    h.press()
    h.outcomes[0]?.onSuccess?.()
    h.press()
    h.outcomes[1]?.onError?.(new ApiError(503, null))
    expect(h.said).toEqual(['resumed', 'Could not resume the watchlist. The platform had a problem. Try again in a moment.'])
  })

  it('hands focus to the schedule button once Resume is gone, as the shell’s rule does', () => {
    expect(schedulePlaces({ paused: true, scheduled: true })).toEqual(['resume', 'schedule', 'schedule-off'])
    expect(placeAfterRedraw(SCHEDULE_PLACES_IN_PAGE_ORDER, 'resume', schedulePlaces({ paused: false, scheduled: true }))).toBe('schedule')
    expect(placeAfterRedraw(SCHEDULE_PLACES_IN_PAGE_ORDER, 'resume', schedulePlaces({ paused: false, scheduled: false }))).toBe('schedule')
  })
})
