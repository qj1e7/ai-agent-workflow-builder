import { describe, expect, it } from 'vitest'
import { deliveryWords, failureText, NOTE_LIMIT, NOTE_ROOM, reportNote } from './support'

describe('the failure text', () => {
  it('drops the error type and keeps every sentence the platform wrote', () => {
    expect(failureText('ModelNeeded: Connect an AI model in Settings.')).toBe('Connect an AI model in Settings.')
    expect(failureText('The workflow called write_action out of order. Reload it from git, then start a new run')).toBe(
      'The workflow called write_action out of order. Reload it from git, then start a new run.',
    )
  })

  it('is empty when nothing is left', () => {
    expect(failureText('')).toBe('')
  })
})

describe('the note on a report', () => {
  it('is what the troubleshooter found, then the person’s words', () => {
    expect(reportNote('It broke.', '  Please look.  ', 'Alice')).toBe('It broke.\n\nNote from Alice: Please look.')
    expect(reportNote('It broke.', '', 'Alice')).toBe('It broke.')
  })

  it('never goes over what the platform keeps, and trims the troubleshooter before the person', () => {
    const note = reportNote('x'.repeat(5000), 'y'.repeat(5000), 'Alice')
    expect(note.length).toBeLessThanOrEqual(NOTE_LIMIT)
    expect(note.endsWith('y'.repeat(NOTE_ROOM))).toBe(true)
  })

  it('keeps the person’s words whole when the display name is very long', () => {
    const own = 'Please look at this before Friday. '.repeat(14).trim().slice(0, NOTE_ROOM)
    const note = reportNote('z'.repeat(5000), own, 'N'.repeat(900))
    expect(note.length).toBeLessThanOrEqual(NOTE_LIMIT)
    expect(note.endsWith(own)).toBe(true)
  })
})

describe('where the card went', () => {
  it('claims Teams only when the platform said it went', () => {
    expect(deliveryWords({ posted_to_teams: true, not_posted_because: null })).toContain('posted in the team’s Teams channel')
    expect(deliveryWords({ posted_to_teams: false, not_posted_because: 'no_channel' })).toContain('No Teams channel is set up')
    expect(deliveryWords({ posted_to_teams: false, not_posted_because: 'failed' })).toContain('Teams did not take it')
    expect(deliveryWords({ posted_to_teams: false, not_posted_because: 'posting' })).toContain('still going')
    expect(deliveryWords({ posted_to_teams: false, not_posted_because: 'no_channel' })).not.toMatch(/was (also )?posted/)
  })
})
