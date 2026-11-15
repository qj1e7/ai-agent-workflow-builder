import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { greeting, today } from '../../shell/today'
import { logClock, runKind, shortTime } from '../run/words'
import { whenWords as settingWhen } from '../settings/settings'
import { dateAndClock, formatterFactory, lineWhen, nextRunAt, runWhen, scheduleZoneName, setTeamZone, teamPlace, teamTime, teamZone, timesZone, zoneWords } from './times'

const NOW = new Date('2026-11-04T07:00:00Z')

describe('with a London team time zone, from /api/v1/me', () => {
  beforeEach(() => setTeamZone('Europe/London'))
  afterEach(() => setTeamZone(undefined))

  it('gives every time without a zone in London, where Singapore would be 8 hours on', () => {
    expect(runWhen('2026-11-04T09:00:00Z', NOW)).toBe('Today, 9:00')
    expect(lineWhen('2026-11-03T23:30:00Z', NOW), 'still the 3rd in London').toBe('Tue 3 Nov')
    expect(dateAndClock('2026-11-23T09:00:00Z')).toBe('Mon 23 Nov, 9:00')
    expect(greeting(new Date('2026-10-28T20:00:00Z'))).toBe('Good evening')
    expect(today(new Date('2026-10-28T20:00:00Z'))).toBe('Wednesday 28 October')
    expect(shortTime('2026-11-13T09:14:00Z')).toBe('Fri 9:14')
    expect(logClock(Date.parse('2026-11-13T08:00:31Z'))).toBe('8:00:31')
    expect(runKind('2026-11-13T08:00:00Z', new Date('2026-11-13T12:00:00Z'))).toBe('Today’s run, 8:00')
    expect(settingWhen('2026-11-13T09:14:00Z')).toBe('Fri 13 Nov, 09:14')
  })

  it('names London as the zone of those times, and names Singapore after a Singapore schedule’s time', () => {
    expect([teamZone(), teamTime(), teamPlace(), timesZone(undefined), zoneWords('')]).toEqual(['Europe/London', 'London time', 'London', 'London time', 'London time.'])
    expect(nextRunAt('2026-11-04T09:00:00Z', NOW, 'Europe/London')).toBe('Today, 9:00')
    expect(nextRunAt('2026-11-04T09:00:00Z', NOW, 'Asia/Singapore')).toBe('Today, 17:00 Singapore time')
    expect([scheduleZoneName('Europe/London'), scheduleZoneName('Asia/Singapore')]).toEqual([null, 'Singapore time'])
    expect(zoneWords('Asia/Singapore')).toBe('Singapore time (SGT).')
  })

  it('gives a zone the browser cannot read in London time, saying so', () => {
    const build = formatterFactory.build
    const spy = vi.spyOn(formatterFactory, 'build').mockImplementation((zone) => {
      if (zone === 'Europe/Kyiv') throw new RangeError(`Invalid time zone specified: ${zone}`)
      return build(zone)
    })
    try {
      expect(nextRunAt('2026-11-04T09:00:00Z', NOW, 'Europe/Kyiv')).toBe('Today, 9:00 London time')
    } finally {
      spy.mockRestore()
    }
  })
})

describe('the team time zone', () => {
  afterEach(() => setTeamZone(undefined))

  it('is Singapore until /api/v1/me names one, and stays Singapore for a name the browser cannot read', () => {
    expect(teamZone()).toBe('Asia/Singapore')
    setTeamZone('Not/AZone')
    expect([teamZone(), teamTime(), runWhen('2026-11-04T09:00:00Z', NOW)]).toEqual(['Asia/Singapore', 'Singapore time', 'Today, 17:00'])
  })
})
