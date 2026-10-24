import saved from '@contracts/fixtures/watchlist/schedule.saved.json'
import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { describe, expect, it } from 'vitest'
import type { ScheduleView, WatchlistView } from '../../api/types'
import { checkSchedule, clockWords, nextWords, ownerWords, scheduleWords, TIME_PROBLEM } from './schedule'

const monday = (statuses as WatchlistView).schedule as ScheduleView
const everyDay = (saved as WatchlistView).schedule as ScheduleView

describe('scheduleWords', () => {
  it('says when the watchlist is checked and who set it', () => {
    expect(scheduleWords(monday)).toBe('Checked every Monday at 9:00, set by Alice.')
    expect(scheduleWords(everyDay)).toBe('Checked every day at 6:30, set by Carol.')
  })

  it('writes the time the way people do', () => {
    expect(clockWords('09:05')).toBe('9:05')
    expect(clockWords('14:30')).toBe('14:30')
    expect(clockWords('00:00')).toBe('0:00')
  })

  it('gives the next check in Singapore time, whatever the browser zone', () => {
    expect(nextWords(monday)).toBe('Next check Mon 23 Nov, 9:00')
    expect(nextWords(everyDay)).toBe('Next check Tue 17 Nov, 6:30')
  })
})

describe('ownerWords', () => {
  it('says the owner cannot approve a scheduled check, to the owner and to everyone else', () => {
    expect(ownerWords(monday, 'bob')).toBe("Scheduled checks count as Alice's work, so Alice can't approve them.")
    expect(ownerWords(monday, 'alice')).toBe('Scheduled checks count as your work, so another Approver approves them.')
  })
})

describe('checkSchedule', () => {
  it('takes a time on a 5-minute step', () => {
    expect(checkSchedule('friday', '07:45')).toEqual({ ok: true, body: { day: 'friday', at: '07:45' } })
    expect(checkSchedule('every_day', '07:45:00')).toEqual({ ok: true, body: { day: 'every_day', at: '07:45' } })
  })

  it('refuses a time the platform would refuse', () => {
    expect(checkSchedule('monday', '09:07')).toEqual({ ok: false, problem: TIME_PROBLEM })
    expect(checkSchedule('monday', '')).toEqual({ ok: false, problem: TIME_PROBLEM })
  })
})
