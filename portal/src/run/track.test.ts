import { describe, expect, it } from 'vitest'
import type { BlockView } from '../api/types'
import type { RunEvent } from '../stream/parse'
import { runTime } from './brand'
import { recording, slice, synthetic, type RecordingName } from './recordings'
import { applyEvent, EMPTY_ROOM, type RoomState } from './room'
import { RELEASE_CHECK, TEST_REGISTRY } from './testing'
import { castLayout, planTrack, trackOf, type Figure, type Scene, type Stop, type Track } from './track'

const RECORDINGS: readonly RecordingName[] = ['success', 'failure', 'rejected']

function fold(events: readonly RunEvent[], from: RoomState = EMPTY_ROOM): RoomState {
  return events.reduce((room, event) => applyEvent(room, event, TEST_REGISTRY), from)
}

function scene(room: RoomState, clock: Partial<Omit<Scene, 'room'>> = {}): Scene {
  return { room, waiting: null, spedUp: false, ...clock }
}

function trackAt(name: RecordingName, seq: number, blocks: readonly BlockView[] = RELEASE_CHECK, clock: Partial<Omit<Scene, 'room'>> = {}): Track {
  return trackOf(scene(fold(slice(name, 1, seq)), clock), blocks)
}

function stop(track: Track, key: string): Stop {
  const found = track.stops.find((candidate) => candidate.key === key)
  if (!found) throw new Error(`no stop ${key} in ${track.stops.map((candidate) => candidate.key).join(', ')}`)
  return found
}

const keys = (track: Track) => track.stops.map((candidate) => candidate.key)
const figures = (track: Track, key: string) => stop(track, key).cast

/** One line per frame: where the parcel is and in what form, who stands where, the gate and the break. */
function outline(track: Track) {
  const keyAt = (index: number | null) => (index === null ? null : (track.stops[index]?.key ?? null))
  return {
    parcel: track.parcel ? `${track.parcel.before ? 'before ' : ''}${keyAt(track.parcel.at)} ${track.parcel.form.is}` : null,
    cast: track.stops.filter((candidate) => candidate.cast.length > 0).map((candidate) => `${candidate.key}: ${candidate.cast.map((figure) => figure.key).join(' ')}`),
    gate: track.gate?.state ?? null,
    breakAt: keyAt(track.breakAt),
  }
}

const ALICE = 'start: person:alice'
const BOTH_AT_READ = 'agent:read_releases: agent:room_lead agent:release_checker'
const CHECKER_AT_READ = 'agent:read_releases: agent:release_checker'
const LEAD_AT_DRAFT = 'draft: agent:room_lead'

type Frames = readonly (readonly [seqs: readonly number[], outline: ReturnType<typeof outline>])[]

const SUCCESS_FRAMES: Frames = [
  [[1, 2, 3], { parcel: 'start request', cast: [ALICE], gate: 'idle', breakAt: null }],
  [[4, 5, 6, 7, 8], { parcel: 'agent:read_releases request', cast: [ALICE, BOTH_AT_READ], gate: 'idle', breakAt: null }],
  [[9, 10, 11], { parcel: 'agent:read_releases found', cast: [ALICE, BOTH_AT_READ], gate: 'idle', breakAt: null }],
  [[12, 13, 14], { parcel: 'draft draft', cast: [ALICE, CHECKER_AT_READ, LEAD_AT_DRAFT], gate: 'idle', breakAt: null }],
  [[15, 16, 17], { parcel: 'before gate draft', cast: [ALICE, CHECKER_AT_READ, LEAD_AT_DRAFT, 'gate: seat:0'], gate: 'waiting', breakAt: null }],
  [[18, 19, 20], { parcel: 'write:jira draft', cast: [ALICE, CHECKER_AT_READ, LEAD_AT_DRAFT, 'gate: person:bob'], gate: 'open', breakAt: null }],
  [[21, 22], { parcel: 'write:jira written', cast: [ALICE, CHECKER_AT_READ, LEAD_AT_DRAFT, 'gate: person:bob'], gate: 'open', breakAt: null }],
  [[23], { parcel: 'done written', cast: [ALICE, CHECKER_AT_READ, LEAD_AT_DRAFT, 'gate: person:bob'], gate: 'open', breakAt: null }],
]

const FAILURE_FRAMES: Frames = [
  [[1, 2, 3], { parcel: 'start request', cast: [ALICE], gate: 'idle', breakAt: null }],
  [[4, 5, 6, 7, 8, 9], { parcel: 'agent:read_releases request', cast: [ALICE, BOTH_AT_READ], gate: 'idle', breakAt: null }],
  [[10, 11, 12], { parcel: 'agent:read_releases stopped', cast: [ALICE, BOTH_AT_READ], gate: 'idle', breakAt: 'agent:read_releases' }],
]

const REJECTED_FRAMES: Frames = [
  ...SUCCESS_FRAMES.slice(0, 5),
  [[18, 19], { parcel: 'before gate declined', cast: [ALICE, CHECKER_AT_READ, LEAD_AT_DRAFT, 'gate: person:bob'], gate: 'declined', breakAt: null }],
]

const STOP_NAMES = ['Started', 'Read GitHub releases', 'Draft ticket', 'Approval gate', 'Jira', 'Done']

describe('trackOf on the release check', () => {
  it('draws six stops before any event: Started, Read GitHub releases, Draft ticket, Approval gate, Jira, Done', () => {
    const plan = planTrack(RELEASE_CHECK)
    expect(plan.stops.map((candidate) => candidate.name)).toEqual(STOP_NAMES)
    expect(keys(plan)).toEqual(['start', 'agent:read_releases', 'draft', 'gate', 'write:jira', 'done'])
    expect(plan.stops.map((candidate) => candidate.state)).toEqual(Array(6).fill('future'))
    expect(plan.parcel).toBeNull()
    expect(stop(plan, 'gate').caption).toEqual({ is: 'needs_person' })
    expect(stop(plan, 'write:jira').caption).toEqual({ is: 'write', status: 'not_yet', references: [] })
    expect(plan.headline).toEqual({ is: 'not_started' })
  })

  it.each([
    ['success', SUCCESS_FRAMES],
    ['failure', FAILURE_FRAMES],
    ['rejected', REJECTED_FRAMES],
  ] as const)('%s: places the parcel, the cast, the gate and the break at every seq', (name, frames) => {
    const seqs = frames.flatMap(([covered]) => covered)
    expect(seqs, 'every seq of the recording has a row').toEqual(recording(name).map((event) => event.seq))
    for (const [covered, expected] of frames) {
      for (const seq of covered) {
        const track = trackAt(name, seq)
        expect(track.stops.map((candidate) => candidate.name), `stops at seq ${seq}`).toEqual(STOP_NAMES)
        expect(outline(track), `seq ${seq}`).toEqual(expected)
      }
    }
  })

  it('seq 1: Alice stands at Started, acting, under the start time, and the run is starting', () => {
    const track = trackAt('success', 1)
    expect(figures(track, 'start')).toEqual([{ key: 'person:alice', is: 'person', id: 'alice', name: 'Alice', acting: true, verdict: null }])
    expect(stop(track, 'start').caption).toEqual({ is: 'time', at: Date.parse('2026-11-03T02:14:00Z') })
    expect(track.headline).toEqual({ is: 'starting' })
    expect(track.subline).toBe('Alice started a run of LangGraph releases.')
    expect(track.stops.map((candidate) => candidate.state)).toEqual(['current', 'future', 'future', 'future', 'future', 'future'])
  })

  it('seq 4: the Room lead brings the Release checker in and acts; the parcel reaches the agent stop', () => {
    const joined = trackAt('success', 4)
    expect(joined.headline, 'before any step, the latest specialist to join is working').toEqual({ is: 'working', agent: 'release_checker' })
    const cast = figures(joined, 'agent:read_releases')
    expect(cast).toEqual([
      { key: 'agent:room_lead', is: 'agent', id: 'room_lead', name: 'Room lead', acting: true, status: 'present' },
      { key: 'agent:release_checker', is: 'agent', id: 'release_checker', name: 'Release checker', acting: false, status: 'present' },
    ])
    expect(castLayout(cast.length).size).toBe('full')
  })

  it('seq 5 and 10: one speech, the speaker acting, at the agent stop; the subline stays on the last story event', () => {
    const asked = trackAt('success', 5)
    expect(asked.speech).toEqual({ seq: 5, stop: 1, speaker: 'room_lead', name: 'Room lead', text: 'Please check langchain-ai/langgraph for releases newer than 1.2.14.' })
    expect(asked.subline).toBe('Room lead brought in Release checker to read the GitHub releases.')
    const reported = trackAt('success', 10)
    expect(reported.speech).toMatchObject({ stop: 1, speaker: 'release_checker', text: 'Two releases are newer than 1.2.14: 1.2.16 and 1.2.15. I suggest one ticket for both.' })
    expect(figures(reported, 'agent:read_releases').map((figure) => figure.is === 'agent' && figure.acting)).toEqual([false, true])
  })

  it('seq 6 and 8: the agent stop shows the running step, and the headline works on it', () => {
    const fetching = trackAt('success', 6)
    expect(stop(fetching, 'agent:read_releases').caption).toEqual({
      is: 'step',
      step: 'fetch_releases',
      summary: 'Release checker is fetching releases from langchain-ai/langgraph.',
    })
    expect(fetching.headline).toEqual({ is: 'working', agent: 'release_checker' })
    expect(fetching.subline).toBe('Release checker is fetching releases from langchain-ai/langgraph.')
    expect(stop(trackAt('success', 7), 'agent:read_releases').caption, 'a finished step with no list shows nothing').toEqual({ is: 'none' })
    expect(stop(trackAt('success', 8), 'agent:read_releases').caption).toEqual({
      is: 'step',
      step: 'find_new',
      summary: 'Release checker is comparing them with the last known tag 1.2.14.',
    })
  })

  it('seq 9: the finding shows as chips on the stop and the parcel, and the headline says what was found', () => {
    const track = trackAt('success', 9)
    expect(stop(track, 'agent:read_releases').caption).toEqual({ is: 'found', items: { is: 'chips', items: ['1.2.16', '1.2.15'] } })
    expect(track.parcel?.form).toEqual({ is: 'found', items: { is: 'chips', items: ['1.2.16', '1.2.15'] } })
    expect(track.headline).toEqual({ is: 'found', step: 'find_new', count: 2 })
  })

  it('seq 12: the parcel is one draft ticket at Draft ticket, and the agent stop keeps its chips', () => {
    const track = trackAt('success', 12)
    expect(track.parcel).toEqual({ at: 2, before: false, form: { is: 'draft', noun: 'ticket', count: 1 } })
    expect(track.headline).toEqual({ is: 'drafting', noun: 'ticket', count: 1 })
    expect(stop(track, 'agent:read_releases').caption).toMatchObject({ is: 'found' })
    expect(track.speech).toBeNull()
  })

  it("seq 15: the parcel waits in front of the gate, one open seat 'Team approver', Jira not written yet, the approval panel at the gate", () => {
    const track = trackAt('success', 15)
    expect(track.gate).toEqual({ stop: 3, state: 'waiting', approvalId: 'apr_01JB8', link: '/approvals/apr_01JB8', openStep: 0, teamsFailed: false })
    expect(figures(track, 'gate')).toEqual([{ key: 'seat:0', is: 'seat', step: 0, label: 'Team approver', open: true }])
    expect(stop(track, 'write:jira').caption).toEqual({ is: 'write', status: 'not_yet', references: [] })
    expect(track.panel).toEqual({ is: 'approval', stop: 3, approvalId: 'apr_01JB8', step: 0 })
    expect(track.headline).toEqual({ is: 'waiting' })
    expect(track.stops.map((candidate) => candidate.state)).toEqual(['passed', 'passed', 'passed', 'current', 'future', 'future'])
  })

  it('seq 17: the gate caption counts the wait the director gives, sped up while a counter outruns the wall', () => {
    expect(stop(trackAt('success', 17, RELEASE_CHECK, { waiting: { since: runTime(0), elapsedMs: 161_000 }, spedUp: true }), 'gate').caption).toEqual({
      is: 'waiting',
      elapsedMs: 161_000,
      spedUp: true,
    })
    expect(stop(trackAt('success', 17), 'gate').caption).toEqual({ is: 'waiting', elapsedMs: 0, spedUp: false })
  })

  it('seq 18: Bob takes the seat and the gate opens; the parcel is at Jira, still a draft, being written', () => {
    const track = trackAt('success', 18)
    expect(figures(track, 'gate')).toEqual([{ key: 'person:bob', is: 'person', id: 'bob', name: 'Bob', acting: true, verdict: 'approve' }])
    expect(stop(track, 'gate').caption).toEqual({ is: 'approved', by: ['Bob'] })
    expect(stop(track, 'write:jira').caption).toEqual({ is: 'write', status: 'writing', references: [] })
    expect(track.headline).toEqual({ is: 'approved', by: ['Bob'] })
    expect(track.panel).toBeNull()
  })

  it('seq 21: MOCK-142 is written at Jira, and the written panel opens there with the title and the approver', () => {
    const track = trackAt('success', 21)
    expect(track.parcel?.form).toEqual({ is: 'written', references: ['MOCK-142'] })
    expect(stop(track, 'write:jira').caption).toEqual({ is: 'write', status: 'written', references: ['MOCK-142'] })
    expect(track.panel).toEqual({
      is: 'written',
      stop: 4,
      lines: [{ connector: 'jira', reference: 'MOCK-142', title: 'New LangGraph releases: 1.2.16, 1.2.15', at: Date.parse('2026-11-03T02:20:26.344Z') }],
      approvedBy: ['Bob'],
    })
    expect(track.headline).toEqual({ is: 'written', lines: [{ reference: 'MOCK-142', connector: 'jira' }] })
  })

  it('seq 23: the parcel rests at Done, every earlier stop passed', () => {
    const track = trackAt('success', 23)
    expect(track.stops.map((candidate) => candidate.state)).toEqual(['passed', 'passed', 'passed', 'passed', 'passed', 'done'])
    expect(track.headline).toEqual({ is: 'written', lines: [{ reference: 'MOCK-142', connector: 'jira' }] })
    expect(track.panel).toMatchObject({ is: 'written', stop: 4 })
    expect(track.cut).toBe(false)
  })

  it('failure seq 10: the line breaks at the agent stop when the agent fails, one beat before the run does', () => {
    const track = trackAt('failure', 10)
    expect(track.breakAt).toBe(1)
    expect(track.cut).toBe(true)
    expect(track.headline).toEqual({ is: 'stopped' })
    expect(stop(track, 'agent:read_releases').state).toBe('failed')
    expect(stop(track, 'agent:read_releases').caption).toEqual({ is: 'stopped', step: 'fetch_releases', errorType: 'UpstreamUnavailable', reason: null })
    expect(stop(track, 'write:jira').caption).toEqual({ is: 'write', status: 'none_written', references: [] })
    expect(track.speech).toBeNull()
    expect(track.panel).toBeNull()
  })

  it('failure seq 12: the run failing opens the trouble panel at the break, and the subline keeps what broke', () => {
    const track = trackAt('failure', 12)
    expect(track.panel).toEqual({ is: 'trouble', stop: 1, retryable: true, attempt: 1 })
    expect(track.subline).toBe('Release checker failed: GitHub was unavailable.')
    expect(stop(track, 'agent:read_releases').caption).toEqual({ is: 'stopped', step: 'fetch_releases', errorType: 'UpstreamUnavailable', reason: 'AgentError' })
  })

  it('rejected seq 18 and 19: declined by Bob in front of the gate, nothing written, the rail cut', () => {
    const decided = trackAt('rejected', 18)
    expect(decided.headline).toEqual({ is: 'declined', by: 'Bob' })
    expect(decided.cut).toBe(true)
    expect(stop(decided, 'gate').caption).toEqual({ is: 'declined', by: 'Bob' })
    expect(figures(decided, 'gate')).toEqual([{ key: 'person:bob', is: 'person', id: 'bob', name: 'Bob', acting: true, verdict: 'decline' }])
    const rejected = trackAt('rejected', 19)
    expect(rejected.headline).toEqual({ is: 'declined', by: 'Bob' })
    expect(stop(rejected, 'write:jira').caption).toEqual({ is: 'write', status: 'none_written', references: [] })
    expect(rejected.panel).toBeNull()
  })
})

describe('trackOf is total and stable', () => {
  it.each(RECORDINGS)('%s: every prefix gives a track, with the release check, and with no blocks', (name) => {
    const events = recording(name)
    for (let to = 0; to <= events.length; to += 1) {
      for (const blocks of [RELEASE_CHECK, []]) {
        const room = fold(events.slice(0, to))
        expect(() => trackOf(scene(room), blocks), `seq ${to} with ${blocks.length} blocks`).not.toThrow()
      }
    }
  })

  it.each(RECORDINGS)('%s: the same frame and blocks give a deep-equal track', (name) => {
    const events = recording(name)
    for (let to = 0; to <= events.length; to += 1) {
      for (const blocks of [RELEASE_CHECK, []]) {
        const room = fold(events.slice(0, to))
        expect(trackOf(scene(room), blocks)).toEqual(trackOf(scene(room), [...blocks]))
      }
    }
  })
})

const BASE = Date.parse('2026-11-05T02:00:00Z')
const LEAD = { kind: 'agent', id: 'room_lead', display: 'Room lead' }
const PLATFORM = { kind: 'platform', id: 'platform', display: 'Platform' }

function event(seq: number, kind: string, actor: Record<string, string>, data: Record<string, unknown>): RunEvent {
  return synthetic('success', { seq, ts: new Date(BASE + seq * 1000).toISOString(), actor, summary: `${kind} ${seq}.`, kind, data })
}

function agent(id: string, display: string) {
  return { kind: 'agent', id, display }
}

function decided(seq: number, step: number, by: string, display: string): RunEvent {
  return event(seq, 'approval_decided', { kind: 'user', id: by, display }, { approval_id: 'apr_x', step, verdict: 'approve', by })
}

function proposal(seq: number, actions: readonly { connector: string; operation: string; line: string }[]): RunEvent {
  return event(seq, 'write_action_proposed', LEAD, { proposal_id: 'prp_x', digest: 'sha256:x', actions })
}

function finished(seq: number, tags: readonly string[]): RunEvent {
  return event(seq, 'agent_step_finished', agent('release_checker', 'Release checker'), { step: 'find_new', result: { tags } })
}

describe('Phase 2 shapes, with no code change', () => {
  it('A synthetic two-step approval_requested (labels "Team approver", "Security approver"): two seats at the gate in order, step 1 locked until step 0 is decided, each showing its own label, then its decider; the gate stays waiting until both approve, open after.', () => {
    const requested = event(15, 'approval_requested', PLATFORM, {
      approval_id: 'apr_x',
      link: '/approvals/apr_x',
      steps: [
        { index: 0, label: 'Team approver', status: 'open', decided_by: null, decided_at: null },
        { index: 1, label: 'Security approver', status: 'waiting', decided_by: null, decided_at: null },
      ],
    })
    const asked = fold([requested], fold(slice('success', 1, 14)))
    const seats = (room: RoomState): readonly Figure[] => figures(trackOf(scene(room), RELEASE_CHECK), 'gate')
    expect(seats(asked)).toEqual([
      { key: 'seat:0', is: 'seat', step: 0, label: 'Team approver', open: true },
      { key: 'seat:1', is: 'seat', step: 1, label: 'Security approver', open: false },
    ])
    expect(trackOf(scene(asked), RELEASE_CHECK).gate?.state).toBe('waiting')

    const first = fold([decided(16, 0, 'bob', 'Bob')], asked)
    expect(seats(first)).toEqual([
      { key: 'person:bob', is: 'person', id: 'bob', name: 'Bob', acting: true, verdict: 'approve' },
      { key: 'seat:1', is: 'seat', step: 1, label: 'Security approver', open: true },
    ])
    expect(trackOf(scene(first), RELEASE_CHECK).gate).toMatchObject({ state: 'waiting', openStep: 1 })

    const both = fold([decided(17, 1, 'carol', 'Carol')], first)
    const track = trackOf(scene(both), RELEASE_CHECK)
    expect(seats(both).map((figure) => figure.key)).toEqual(['person:bob', 'person:carol'])
    expect(track.gate?.state).toBe('open')
    expect(stop(track, 'gate').caption).toEqual({ is: 'approved', by: ['Bob', 'Carol'] })
    expect(track.parcel?.at).toBe(keys(track).indexOf('write:jira'))
  })

  it("A synthetic proposal with a Confluence and a Jira action: two write stops after the gate, in proposal order, the seeded Jira stop keeps its key; with only Jira, the release check's six stops do not change key or position.", () => {
    const both = fold(
      [
        proposal(12, [
          { connector: 'confluence', operation: 'update_page', line: 'Update Confluence page: Releases' },
          { connector: 'jira', operation: 'create_ticket', line: 'Create Jira ticket in MOCK: Releases' },
        ]),
      ],
      fold(slice('success', 1, 11)),
    )
    const track = trackOf(scene(both), RELEASE_CHECK)
    expect(keys(track)).toEqual(['start', 'agent:read_releases', 'draft', 'gate', 'write:confluence', 'write:jira', 'done'])
    expect(track.stops.map((candidate) => candidate.name).slice(4, 6)).toEqual(['Confluence', 'Jira'])
    expect(stop(track, 'draft').name).toBe('Draft')

    const before = trackAt('success', 11)
    for (const seq of [12, 15, 18, 21, 23]) expect(keys(trackAt('success', seq)), `seq ${seq}`).toEqual(keys(before))
  })

  it('A synthetic stop holding three agents with different statuses (working, done, stopped): three figures, each its own status, and castLayout says compact; the release check\'s two figures say full.', () => {
    const blocks: readonly BlockView[] = [
      { key: 'read_access', name: 'Read access lists', description: 'Readers collect who can reach Entra, the admin tools and GitLab.', kind: 'agent' },
      ...RELEASE_CHECK.slice(1),
    ]
    const room = fold([
      event(1, 'run_created', { kind: 'user', id: 'alice', display: 'Alice' }, { use_case_id: 'uc_x', use_case_version: 1, started_by: 'alice' }),
      event(2, 'agent_step_started', agent('entra_reader', 'Entra reader'), { step: 'read_entra' }),
      event(3, 'agent_step_started', agent('admin_reader', 'Admin reader'), { step: 'read_admin' }),
      event(4, 'agent_step_finished', agent('admin_reader', 'Admin reader'), { step: 'read_admin', result: {} }),
      event(5, 'agent_step_started', agent('gitlab_reader', 'GitLab reader'), { step: 'read_gitlab' }),
      event(6, 'agent_failed', agent('gitlab_reader', 'GitLab reader'), { step: 'read_gitlab', error_type: 'UpstreamUnavailable', message: 'down', retryable: true }),
    ])
    const cast = figures(trackOf(scene(room), blocks), 'agent:read_access')
    expect(cast.map((figure) => (figure.is === 'agent' ? [figure.id, figure.status] : figure.key))).toEqual([
      ['entra_reader', 'working'],
      ['admin_reader', 'done'],
      ['gitlab_reader', 'stopped'],
    ])
    expect(castLayout(cast.length).size).toBe('compact')
    expect(castLayout(figures(trackAt('success', 4), 'agent:read_releases').length).size).toBe('full')
  })

  it('A finding of 312 items keeps all 312 (finding.ts no longer drops lists over 6) and the parcel and stop show one count chip ("312 found"); 4 items show chips; 5 show the count.', () => {
    const tags = Array.from({ length: 312 }, (_, i) => `1.${Math.floor(i / 10)}.${i % 10}`)
    const room = fold([finished(9, tags)], fold(slice('success', 1, 8)))
    expect(room.finding?.items).toHaveLength(312)
    const track = trackOf(scene(room), RELEASE_CHECK)
    expect(track.parcel?.form).toEqual({ is: 'found', items: { is: 'count', count: 312 } })
    expect(stop(track, 'agent:read_releases').caption).toEqual({ is: 'found', items: { is: 'count', count: 312 } })

    const shown = (count: number) => trackOf(scene(fold([finished(9, tags.slice(0, count))], fold(slice('success', 1, 8)))), RELEASE_CHECK).parcel?.form
    expect(shown(4)).toEqual({ is: 'found', items: { is: 'chips', items: tags.slice(0, 4) } })
    expect(shown(5)).toEqual({ is: 'found', items: { is: 'count', count: 5 } })
  })
})

describe('trackOf on the edges of the contract', () => {
  it('shows a chip list only when every item is short, else the count', () => {
    const long = 'x'.repeat(33)
    const room = fold([finished(9, ['1.2.16', long])], fold(slice('success', 1, 8)))
    expect(trackOf(scene(room), RELEASE_CHECK).parcel?.form).toEqual({ is: 'found', items: { is: 'count', count: 2 } })
  })

  it('keeps a seeded write stop the proposal does not use, as not needed', () => {
    const blocks: readonly BlockView[] = [
      ...RELEASE_CHECK,
      { key: 'update_page', name: 'Update Confluence page', description: '', kind: 'write_action' },
    ]
    expect(keys(trackAt('success', 11, blocks)).slice(4, 6)).toEqual(['write:jira', 'write:confluence'])
    const track = trackAt('success', 23, blocks)
    expect(keys(track).slice(4, 6)).toEqual(['write:jira', 'write:confluence'])
    expect(stop(track, 'write:confluence')).toMatchObject({ state: 'not_needed', caption: { is: 'not_needed' } })
  })

  it('lets the first connector the blocks do not name claim an unnamed write block, keeping its key', () => {
    const blocks: readonly BlockView[] = [...RELEASE_CHECK.slice(0, 2), { key: 'record_it', name: 'Record the releases', description: '', kind: 'write_action' }]
    expect(keys(trackAt('success', 11, blocks))[4]).toBe('write:record_it')
    const track = trackAt('success', 12, blocks)
    expect(track.stops[4]).toMatchObject({ key: 'write:record_it', name: 'Jira' })
  })

  it('stands agents that two agent blocks name at their own blocks, and an unnamed agent at the next free block', () => {
    const blocks: readonly BlockView[] = [
      { key: 'read_a', name: 'Read A', description: 'The B reader reads B.', kind: 'agent' },
      { key: 'read_b', name: 'Read B', description: 'The A reader reads A.', kind: 'agent' },
      { key: 'read_c', name: 'Read C', description: 'Someone reads C.', kind: 'agent' },
    ]
    const room = fold([
      event(1, 'run_created', { kind: 'user', id: 'alice', display: 'Alice' }, { use_case_id: 'uc_x', use_case_version: 1, started_by: 'alice' }),
      event(2, 'agent_step_started', agent('c_reader', 'C reader'), { step: 'read' }),
      event(3, 'agent_step_started', agent('a_reader', 'A reader'), { step: 'read' }),
      event(4, 'agent_step_started', agent('b_reader', 'B reader'), { step: 'read' }),
    ])
    const track = trackOf(scene(room), blocks)
    expect(['agent:read_a', 'agent:read_b', 'agent:read_c'].map((key) => figures(track, key).map((figure) => figure.key))).toEqual([
      ['agent:b_reader'],
      ['agent:a_reader'],
      ['agent:c_reader'],
    ])
  })

  it('stands in a Work, Draft and Approval stop for events the blocks do not foresee', () => {
    const track = trackAt('success', 23, [])
    expect(track.stops.map((candidate) => [candidate.key, candidate.name])).toEqual([
      ['start', 'Started'],
      ['agent:work', 'Work'],
      ['draft', 'Draft ticket'],
      ['gate', 'Approval'],
      ['write:jira', 'Jira'],
      ['done', 'Done'],
    ])
    expect(keys(trackAt('success', 1, []))).toEqual(['start', 'done'])
  })

  it('breaks the line at Draft ticket when the run fails while the proposal is prepared', () => {
    const failed = event(13, 'run_failed', PLATFORM, { stage: 'proposed', reason: 'UnboundIntent', retryable: false, message: 'no allowed action' })
    const track = trackOf(scene(fold([failed], fold(slice('success', 1, 12)))), RELEASE_CHECK)
    expect(track.breakAt).toBe(2)
    expect(track.parcel).toMatchObject({ at: 2, form: { is: 'stopped' } })
    expect(track.panel).toEqual({ is: 'trouble', stop: 2, retryable: false, attempt: 1 })
  })

  it('puts the parcel back at Started as a request after a retry of the work leg, with no cast and no gate state, attempt 2', () => {
    const retried = event(13, 'run_retried', { kind: 'user', id: 'alice', display: 'Alice' }, { leg: 'work', attempt: 2 })
    const track = trackOf(scene(fold([retried], fold(recording('failure')))), RELEASE_CHECK)
    expect(track.parcel).toEqual({ at: 0, before: false, form: { is: 'request' } })
    expect(track.stops.flatMap((candidate) => candidate.cast.map((figure) => figure.key))).toEqual(['person:alice'])
    expect(track.gate?.state).toBe('idle')
    expect(track.breakAt).toBeNull()
    expect(track.attempt).toBe(2)
  })

  it('returns the parcel to the write stop after a retry of the act leg, the gate still open', () => {
    const denied = event(21, 'write_action_denied', { kind: 'safety_checker', id: 'safety_checker', display: 'Safety checker' }, { reason: 'digest_mismatch', detail: 'mismatch' })
    const blocked = trackOf(scene(fold([denied], fold(slice('success', 1, 20)))), RELEASE_CHECK)
    expect(blocked.breakAt).toBe(4)
    expect(stop(blocked, 'write:jira').caption).toEqual({ is: 'write', status: 'blocked', references: [] })
    const retried = event(22, 'run_retried', { kind: 'user', id: 'alice', display: 'Alice' }, { leg: 'act', attempt: 2 })
    const track = trackOf(scene(fold([denied, retried], fold(slice('success', 1, 20)))), RELEASE_CHECK)
    expect(track.parcel).toEqual({ at: 4, before: false, form: { is: 'draft', noun: 'ticket', count: 1 } })
    expect(track.gate?.state).toBe('open')
    expect(track.breakAt).toBeNull()
  })

  it('marks the gate when the Teams post failed, so the view can offer the approval page instead', () => {
    const failed = event(17, 'approval_announce_failed', PLATFORM, { approval_id: 'apr_01JB8', channel: 'CODESparks Ops', message: 'Teams did not answer' })
    const track = trackOf(scene(fold([failed], fold(slice('success', 1, 16)))), RELEASE_CHECK)
    expect(track.gate).toMatchObject({ state: 'waiting', teamsFailed: true, link: '/approvals/apr_01JB8' })
  })

  it('marks the write stops not needed when there was nothing to write', () => {
    const done = event(12, 'run_succeeded', PLATFORM, { outcome: 'nothing_to_write' })
    const track = trackOf(scene(fold([done], fold(slice('success', 1, 11)))), RELEASE_CHECK)
    expect(track.stops.map((candidate) => candidate.state)).toEqual(['passed', 'passed', 'not_needed', 'not_needed', 'not_needed', 'done'])
    expect(track.headline).toEqual({ is: 'nothing_to_write' })
  })
})

describe('castLayout', () => {
  it('draws up to two figures full size, three or four compact, and three plus "+N" above four', () => {
    expect([1, 2, 3, 4, 5, 9].map(castLayout)).toEqual([
      { size: 'full', shown: 1, more: 0 },
      { size: 'full', shown: 2, more: 0 },
      { size: 'compact', shown: 3, more: 0 },
      { size: 'compact', shown: 4, more: 0 },
      { size: 'compact', shown: 3, more: 2 },
      { size: 'compact', shown: 3, more: 6 },
    ])
  })
})
