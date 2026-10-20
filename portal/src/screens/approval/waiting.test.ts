import { describe, expect, it } from 'vitest'
import { waitedMs, waitingWords, atWords } from './waiting'
import { waitingApprovals } from './approvals'
import type { RunView } from '../../api/types'

describe('how long a run has waited', () => {
  const since = '2026-11-03T02:14:10.612Z'

  it('counts from the moment the approval was asked for', () => {
    const clock = Date.parse('2026-11-03T02:20:23.612Z')
    expect(waitingWords(waitedMs(clock, since))).toBe('Waiting 6 min 13 s')
  })

  it('never shows a negative wait when the clock is a little behind', () => {
    expect(waitingWords(waitedMs(Date.parse(since) - 500, since))).toBe('Waiting 0 s')
  })
})

describe('atWords', () => {
  it('says only the time for something decided today and adds the day otherwise', () => {
    const iso = '2026-11-03T02:20:23Z'
    expect(atWords(iso, Date.parse('2026-11-03T05:00:00Z'))).toMatch(/^at \d\d:\d\d$/)
    expect(atWords(iso, Date.parse('2026-11-06T05:00:00Z'))).toMatch(/^on \d+ \w+ at \d\d:\d\d$/)
  })
})

describe('waitingApprovals', () => {
  function run(id: string, state: RunView['state'], updated: string): RunView {
    return {
      run_id: id,
      use_case_id: 'uc',
      use_case_name: 'Name',
      use_case_version: 1,
      started_by: 'alice',
      started_at: updated,
      updated_at: updated,
      last_seq: 1,
      events_url: '/e',
      state,
    } as RunView
  }

  it('keeps only runs waiting for a decision, longest wait first', () => {
    const runs = [
      run('newer', 'awaiting_approval', '2026-11-03T03:00:00Z'),
      run('done', 'succeeded', '2026-11-03T01:00:00Z'),
      run('older', 'awaiting_approval', '2026-11-03T02:00:00Z'),
      run('failed', 'failed', '2026-11-03T02:30:00Z'),
    ]
    expect(waitingApprovals(runs).map((each) => each.run_id)).toEqual(['older', 'newer'])
  })
})
