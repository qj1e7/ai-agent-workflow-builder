import { describe, expect, it } from 'vitest'
import type { RunEvent } from '../stream/parse'
import { agentId, connectorKey, runTime, userId } from './brand'
import { captionWords, figureWords, headlineWords, parcelShortWords, parcelWords, splitActionLine, stopWords, teamsWords } from './describe'
import { recording, slice, synthetic, type RecordingName } from './recordings'
import { applyEvent, EMPTY_ROOM, type RoomState } from './room'
import { RELEASE_CHECK, TEST_REGISTRY } from './testing'
import { trackOf, type Gate, type Stop, type Track } from './track'

const ALICE = { canDecide: false }
const BOB = { canDecide: true }

function fold(events: readonly RunEvent[], from: RoomState = EMPTY_ROOM): RoomState {
  return events.reduce((room, event) => applyEvent(room, event, TEST_REGISTRY), from)
}

function trackAt(name: RecordingName, seq: number, clock: { waiting?: { since: number; elapsedMs: number }; spedUp?: boolean } = {}): Track {
  const waiting = clock.waiting ? { since: runTime(clock.waiting.since), elapsedMs: clock.waiting.elapsedMs } : null
  return trackOf({ room: fold(slice(name, 1, seq)), waiting, spedUp: clock.spedUp ?? false }, RELEASE_CHECK)
}

function stop(track: Track, key: string): Stop {
  const found = track.stops.find((candidate) => candidate.key === key)
  if (!found) throw new Error(`no stop ${key}`)
  return found
}

const caption = (track: Track, key: string) => captionWords(stop(track, key).caption)

describe('headlineWords on the recordings', () => {
  it('reads the release check from start to written', () => {
    const headline = (at: number, viewer = ALICE) => headlineWords(trackAt('success', at).headline, viewer)
    expect(headline(1)).toBe('Starting')
    expect(headline(4), 'before any step, the Release checker has just joined').toBe('Looking for new releases')
    expect(headline(6)).toBe('Looking for new releases')
    expect(headline(8)).toBe('Looking for new releases')
    expect(headline(9)).toBe('Found 2 new releases')
    expect(headline(11)).toBe('Found 2 new releases')
    expect(headline(12)).toBe('Drafting one ticket')
    expect(headline(15)).toBe('Waiting for an Approver')
    expect(headline(15, BOB)).toBe('Waiting for your approval')
    expect(headline(18)).toBe('Approved by Bob')
    expect(headline(21)).toBe('MOCK-142 is in Jira')
    expect(headline(23)).toBe('MOCK-142 is in Jira')
  })

  it('reads a failure and a rejection', () => {
    expect(headlineWords(trackAt('failure', 10).headline, ALICE)).toBe('The run stopped')
    expect(headlineWords(trackAt('failure', 12).headline, ALICE)).toBe('The run stopped')
    expect(headlineWords(trackAt('rejected', 18).headline, ALICE)).toBe('Declined by Bob')
    expect(headlineWords(trackAt('rejected', 19).headline, BOB)).toBe('Declined by Bob')
  })
})

describe('headlineWords on every kind', () => {
  it('counts what was found and drafted, in words for one', () => {
    expect(headlineWords({ is: 'found', step: 'find_new', count: 1 }, ALICE)).toBe('Found 1 new release')
    expect(headlineWords({ is: 'found', step: 'count_users', count: 312 }, ALICE)).toBe('Found 312')
    expect(headlineWords({ is: 'drafting', noun: 'ticket', count: 2 }, ALICE)).toBe('Drafting 2 tickets')
    expect(headlineWords({ is: 'drafting', noun: '', count: 2 }, ALICE)).toBe('Drafting')
  })

  it('names every approver and every place written', () => {
    expect(headlineWords({ is: 'approved', by: ['Bob', 'Carol'] }, ALICE)).toBe('Approved by Bob and Carol')
    expect(
      headlineWords(
        {
          is: 'written',
          lines: [
            { reference: 'PAGE-7', connector: connectorKey('confluence') },
            { reference: 'MOCK-142', connector: connectorKey('jira') },
          ],
        },
        ALICE,
      ),
    ).toBe('Written to Confluence and Jira')
    expect(headlineWords({ is: 'nothing_to_write' }, ALICE)).toBe('Nothing to write')
  })

  it('reads Working for an agent the table does not know, and before anyone joins', () => {
    expect(headlineWords({ is: 'working', agent: agentId('entra_reader') }, ALICE)).toBe('Working')
    expect(headlineWords({ is: 'working', agent: null }, ALICE)).toBe('Working')
  })
})

describe('captionWords', () => {
  it('shows the start time in the viewer zone, and the running step in short words', () => {
    const startedAt = Date.parse('2026-11-03T02:14:00Z')
    const local = new Intl.DateTimeFormat('en-SG', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(startedAt))
    expect(caption(trackAt('success', 1), 'start')).toBe(local)
    expect(caption(trackAt('success', 6), 'agent:read_releases')).toBe('Reading GitHub')
    expect(caption(trackAt('success', 8), 'agent:read_releases')).toBe('Comparing with 1.2.14')
    expect(caption(trackAt('success', 9), 'agent:read_releases')).toBe('1.2.16, 1.2.15')
  })

  it("shows a step the table does not know by its event's summary", () => {
    expect(captionWords({ is: 'step', step: 'read_entra', summary: 'Entra reader is reading the directory.' })).toBe('Entra reader is reading the directory.')
  })

  it('says GitHub unavailable where the reading step failed on GitHub, and Stopped here otherwise', () => {
    expect(caption(trackAt('failure', 10), 'agent:read_releases')).toBe('GitHub unavailable')
    expect(captionWords({ is: 'stopped', step: 'fetch_releases', errorType: 'Timeout', reason: null })).toBe('Stopped here')
    expect(captionWords({ is: 'stopped', step: null, errorType: null, reason: 'WorkflowNodeError' })).toBe('Stopped here')
  })

  it('reads the gate: needs a person, the waiting counter, then the decision', () => {
    expect(caption(trackAt('success', 12), 'gate')).toBe('Needs a person')
    const paused = trackAt('success', 17, { waiting: { since: 0, elapsedMs: 161_000 }, spedUp: true })
    expect(caption(paused, 'gate')).toBe('Waiting 2:41')
    expect(caption(trackAt('success', 18), 'gate')).toBe('Approved by Bob')
    expect(caption(trackAt('rejected', 18), 'gate')).toBe('Declined by Bob')
  })

  it('reads a write stop from nothing written yet to written', () => {
    expect(caption(trackAt('success', 15), 'write:jira')).toBe('Nothing written yet')
    expect(caption(trackAt('success', 18), 'write:jira')).toBe('Writing')
    expect(caption(trackAt('success', 21), 'write:jira')).toBe('Written')
    expect(caption(trackAt('rejected', 19), 'write:jira')).toBe('Nothing written')
    expect(captionWords({ is: 'write', status: 'blocked', references: [] })).toBe('Blocked')
    expect(captionWords({ is: 'not_needed' })).toBe('Not needed')
  })
})

describe('teamsWords', () => {
  it('speaks only when the Teams post failed', () => {
    const gate: Gate = { stop: 3, state: 'waiting', approvalId: 'apr_x', link: '/approvals/apr_x', openStep: 0, teamsFailed: true }
    expect(teamsWords(gate)).toBe('Teams post failed')
    expect(teamsWords({ ...gate, teamsFailed: false })).toBeNull()
  })
})

describe('parcelWords', () => {
  it('reads the parcel from request to the written reference', () => {
    const form = (at: number, name: RecordingName = 'success') => {
      const parcel = trackAt(name, at).parcel
      return parcel ? parcelWords(parcel.form) : null
    }
    expect(form(1)).toBe('Request')
    expect(form(9)).toBe('1.2.16, 1.2.15')
    expect(form(12)).toBe('Draft ticket')
    expect(form(21)).toBe('MOCK-142')
    expect(form(19, 'rejected')).toBe('Not written')
    expect(form(10, 'failure')).toBe('Stopped')
    expect(parcelWords({ is: 'written', references: { is: 'count', count: 2 } }), 'several keys read as a count').toBe('2 written')
  })

  it('says a few words when the column is too narrow for the full parcel', () => {
    expect(parcelShortWords({ is: 'found', items: { is: 'chips', items: ['1.2.16', '1.2.15'] } })).toBe('2 found')
    expect(parcelShortWords({ is: 'draft', noun: 'ticket', count: 1 })).toBe('Draft')
    expect(parcelShortWords({ is: 'written', references: { is: 'chips', items: ['MOCK-142'] } })).toBe('Written')
    expect(parcelShortWords({ is: 'written', references: { is: 'count', count: 2 } })).toBe('2 written')
    expect(parcelShortWords({ is: 'declined' })).toBe('Not written')
  })

  it('shows one count chip for a long finding: "312 found"', () => {
    const tags = Array.from({ length: 312 }, (_, i) => `tag-${i}`)
    const found = synthetic('success', {
      seq: 9,
      ts: '2026-11-03T02:14:04.955Z',
      actor: { kind: 'agent', id: 'release_checker', display: 'Release checker' },
      summary: 'Release checker found 312 tags.',
      kind: 'agent_step_finished',
      data: { step: 'find_new', result: { tags } },
    })
    const track = trackOf({ room: fold([found], fold(slice('success', 1, 8))), waiting: null, spedUp: false }, RELEASE_CHECK)
    expect(track.parcel ? parcelWords(track.parcel.form) : null).toBe('312 found')
    expect(caption(track, 'agent:read_releases')).toBe('312 found')
  })
})

describe('stopWords and figureWords', () => {
  it('say where the work is and what each stop shows, for a screen reader', () => {
    const paused = trackAt('success', 17, { waiting: { since: 0, elapsedMs: 161_000 }, spedUp: true })
    const words = paused.stops.map((candidate, index) => stopWords(candidate, paused.parcel?.at === index ? paused.parcel.form : null))
    expect(words).toEqual([
      expect.stringMatching(/^Finished\. \d{2}:\d{2}\.$/),
      'Finished. 1.2.16, 1.2.15.',
      'Finished.',
      'The work is here: Draft ticket. Waiting 2:41. Sped up.',
      'Not reached. Nothing written yet.',
      'Not reached.',
    ])
    const failed = trackAt('failure', 12)
    expect(stopWords(stop(failed, 'agent:read_releases'), failed.parcel?.form ?? null)).toBe('Stopped here: Stopped. GitHub unavailable.')
  })

  it('name each figure with its state', () => {
    expect(figureWords({ key: 'agent:release_checker', is: 'agent', id: agentId('release_checker'), name: 'Release checker', acting: false, status: 'working' })).toBe('Release checker, working')
    expect(figureWords({ key: 'seat:0', is: 'seat', step: 0, label: 'Team approver', open: true })).toBe('Team approver, waiting for a decision')
    expect(figureWords({ key: 'seat:1', is: 'seat', step: 1, label: 'Security approver', open: false })).toBe('Security approver, after the step before')
    expect(figureWords({ key: 'person:bob', is: 'person', id: userId('bob'), name: 'Bob', acting: true, verdict: 'approve' })).toBe('Bob, approved')
    expect(figureWords({ key: 'person:alice', is: 'person', id: userId('alice'), name: 'Alice', acting: false, verdict: null })).toBe('Alice, started the run')
  })
})

describe('splitActionLine', () => {
  it("splits the proposal's line into the action and the title at the first colon, and keeps a line without one whole", () => {
    expect(splitActionLine('Create Jira ticket in MOCK: New LangGraph releases: 1.2.16, 1.2.15')).toEqual({
      action: 'Create Jira ticket in MOCK',
      title: 'New LangGraph releases: 1.2.16, 1.2.15',
    })
    expect(splitActionLine('Create a ticket')).toEqual({ action: null, title: 'Create a ticket' })
    expect(splitActionLine(': untitled')).toEqual({ action: null, title: ': untitled' })
    expect(splitActionLine('Create a ticket: ')).toEqual({ action: null, title: 'Create a ticket: ' })
  })
})

it('has every recording read without an empty headline', () => {
  for (const name of ['success', 'failure', 'rejected'] as const) {
    for (let at = 0; at <= recording(name).length; at += 1) {
      expect(headlineWords(trackAt(name, at).headline, ALICE), `${name} seq ${at}`).not.toBe('')
    }
  }
})
