import { describe, expect, it } from 'vitest'
import type { RunEvent } from '../stream/parse'
import { agentId, connectorKey } from './brand'
import { recording, renumber, slice, synthetic } from './recordings'
import { applyEvent, EMPTY_ROOM, openStep, type RoomState } from './room'
import { TEST_REGISTRY } from './testing'

function fold(events: readonly RunEvent[], from: RoomState = EMPTY_ROOM): RoomState {
  return events.reduce((room, event) => applyEvent(room, event, TEST_REGISTRY), from)
}

const success = (to: number) => fold(slice('success', 1, to))
const failure = (to: number) => fold(slice('failure', 1, to))
const at = (seq: number) => recording('success')[seq - 1]?.at ?? 0

const ROOM_LEAD = agentId('room_lead')
const CHECKER = agentId('release_checker')
const JIRA = connectorKey('jira')
const CONFLUENCE = connectorKey('confluence')

function seatOf(room: RoomState, id: string) {
  const seat = room.agents.find((candidate) => candidate.id === id)
  if (!seat) throw new Error(`${id} is not seated`)
  return seat
}

describe('applyEvent on the recordings', () => {
  it('starts with the starter at the start and no agent yet', () => {
    const room = success(1)
    expect(room.phase).toEqual({ name: 'pending' })
    expect(room.starter).toEqual({ id: 'alice', display: 'Alice' })
    expect(room.agents).toEqual([])
    expect(room.work).toEqual({ at: 'start' })
    expect(room.latest?.summary).toBe('Alice started a run of LangGraph releases.')
  })

  it('ends the success recording written at the end, with MOCK-142 and the time it was written', () => {
    const room = fold(recording('success'))
    expect(room.phase).toEqual({ name: 'succeeded', outcome: 'written' })
    expect(room.work).toEqual({ at: 'done' })
    expect(room.ticket?.lines[0]).toMatchObject({ reference: 'MOCK-142', writtenAt: at(21) })
    expect(room.approval?.steps[0]?.state).toMatchObject({ is: 'approved', by: { id: 'bob', display: 'Bob' } })
    expect(room.agents.map((seat) => seat.id)).toEqual([ROOM_LEAD, CHECKER])
    expect(room.latest?.summary).toBe('The run succeeded. 1 write action was done.')
    expect(room.speech).toBeNull()
  })

  it('waits at the gate with the open step and the Teams post', () => {
    const room = success(17)
    const open = openStep(room)
    expect(open?.index).toBe(0)
    expect(open?.label).toBe('Team approver')
    expect(open?.state.since).toBe(at(15))
    expect(room.approval?.teams).toEqual({ is: 'posted', channel: 'CODESparks Ops' })
    expect(room.work).toEqual({ at: 'gate' })
    expect(room.speech).toBeNull()
  })

  it('moves the work from the start to the agents, the draft, the gate, the write and the end', () => {
    const where = (to: number) => success(to).work
    expect(where(1)).toEqual({ at: 'start' })
    expect(where(4)).toEqual({ at: 'agent', id: CHECKER })
    expect(where(11)).toEqual({ at: 'agent', id: CHECKER })
    expect(where(12)).toEqual({ at: 'draft' })
    expect(where(15)).toEqual({ at: 'gate' })
    expect(where(18)).toEqual({ at: 'write', connector: JIRA })
    expect(where(21)).toEqual({ at: 'write', connector: JIRA })
    expect(where(23)).toEqual({ at: 'done' })
  })

  it('stands each agent where it last acted: the Room lead with the Release checker, then at the draft it proposed', () => {
    const joined = success(4)
    expect(joined.agents.map((seat) => [seat.id, seat.role, seat.at])).toEqual([
      [ROOM_LEAD, 'host', { at: 'agent', id: CHECKER }],
      [CHECKER, 'specialist', { at: 'agent', id: CHECKER }],
    ])
    const proposed = success(12)
    expect(seatOf(proposed, ROOM_LEAD).at).toEqual({ at: 'draft' })
    expect(seatOf(proposed, CHECKER).at).toEqual({ at: 'agent', id: CHECKER })
  })

  it("keeps each agent's latest step, running then finished, with the event's summary", () => {
    expect(seatOf(success(6), CHECKER)).toMatchObject({
      status: 'working',
      step: { seq: 6, step: 'fetch_releases', state: 'running', summary: 'Release checker is fetching releases from langchain-ai/langgraph.' },
    })
    expect(seatOf(success(7), CHECKER)).toMatchObject({ status: 'done', step: { seq: 7, step: 'fetch_releases', state: 'finished' } })
    expect(seatOf(success(8), CHECKER).step).toMatchObject({
      step: 'find_new',
      state: 'running',
      summary: 'Release checker is comparing them with the last known tag 1.2.14.',
    })
  })

  it('sets the subline from step starts and other story events, and leaves it alone for speech', () => {
    expect(success(4).latest?.summary).toBe('Room lead brought in Release checker to read the GitHub releases.')
    expect(success(5).latest, 'a message does not change the subline').toEqual(success(4).latest)
    expect(success(6).latest?.summary).toBe('Release checker is fetching releases from langchain-ai/langgraph.')
    expect(success(9).latest?.summary).toBe('Release checker found 2 new releases: 1.2.16, 1.2.15.')
    expect(success(11).latest).toEqual(success(9).latest)
  })

  it('keeps what broke in the subline when an agent stopped, and takes the failure itself when none did', () => {
    expect(failure(12).latest?.summary, 'agent_failed already names what broke').toBe('Release checker failed: GitHub was unavailable.')
    const failed = synthetic('success', {
      seq: 19,
      ts: '2026-11-03T02:20:25Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run failed while writing. Jira did not answer.',
      kind: 'run_failed',
      data: { stage: 'acting', reason: 'WriteFailed', retryable: true, message: 'Jira did not answer' },
    })
    expect(fold([failed], success(18)).latest?.summary, 'not the approval that came before').toBe('The run failed while writing. Jira did not answer.')
  })

  it('puts only agent_message text in an agent mouth', () => {
    expect(success(5).speech).toEqual({ seq: 5, speaker: ROOM_LEAD, text: 'Please check langchain-ai/langgraph for releases newer than 1.2.14.' })
    expect(success(4).speech).toBeNull()
  })

  it('clears speech when a step starts or finishes, when the phase changes, and when an agent fails', () => {
    expect(success(5).speech?.speaker).toBe(ROOM_LEAD)
    expect(success(6).speech).toBeNull()
    expect(success(10).speech?.speaker).toBe(CHECKER)
    expect(success(12).phase.name).toBe('proposed')
    expect(success(12).speech).toBeNull()
    expect(failure(9).speech?.text).toMatch(/^GitHub answered 503 Service Unavailable \(try 3/)
    expect(failure(10).speech, 'the agent failing clears its last words').toBeNull()
  })

  it.each(['success', 'failure', 'rejected'] as const)('%s: plumbing changes nothing visible', (name) => {
    const events = recording(name)
    const withoutPlumbing = events.filter(
      (event) => !['leg_dispatched', 'step_started', 'step_finished', 'step_retried'].includes(event.kind),
    )
    for (let to = 1; to <= events.length; to += 1) {
      const full = fold(events.filter((event) => event.seq <= to))
      const lean = fold(withoutPlumbing.filter((event) => event.seq <= to))
      expect({ ...full, cursor: 0 }).toEqual({ ...lean, cursor: 0 })
    }
  })

  it('keeps a finding from the step that returned a list, through the talk and the proposal', () => {
    expect(success(7).finding, 'a count and a version are not a finding').toBeNull()
    const found = success(9).finding
    expect(found).toEqual({ agent: CHECKER, step: 'find_new', items: ['1.2.16', '1.2.15'] })
    expect(success(11).finding).toEqual(found)
    expect(success(17).finding).toEqual(found)
  })

  it('stops the agent that failed with its step and error, and seats no troubleshooter when the run fails', () => {
    const stopped = failure(10)
    expect(seatOf(stopped, CHECKER)).toMatchObject({
      status: 'stopped',
      at: { at: 'agent', id: CHECKER },
      step: { seq: 10, step: 'fetch_releases', state: 'failed', errorType: 'UpstreamUnavailable' },
    })
    const failed = failure(12)
    expect(failed.phase).toMatchObject({ name: 'failed', reason: 'AgentError', retryable: true, stage: 'working' })
    expect(failed.agents.map((seat) => seat.id)).toEqual([ROOM_LEAD, CHECKER])
    expect(failed.work).toEqual({ at: 'agent', id: CHECKER })
  })

  it('ends a rejection at the gate, declined by Bob, with nothing written', () => {
    const room = fold(recording('rejected'))
    expect(room.phase).toEqual({ name: 'rejected', by: { id: 'bob', display: 'Bob' }, step: 0 })
    expect(room.work).toEqual({ at: 'gate' })
    expect(room.approval?.steps[0]?.state).toMatchObject({ is: 'declined', by: { id: 'bob', display: 'Bob' } })
    expect(room.ticket?.lines.every((line) => line.reference === null)).toBe(true)
  })

  it('acts once the approver says yes, then records the reference written', () => {
    const decided = success(18)
    expect(decided.phase.name).toBe('acting')
    expect(openStep(decided)).toBeNull()
    expect(decided.ticket?.lines[0]).toMatchObject({ reference: null, writtenAt: null })
    expect(success(21).ticket?.lines[0]?.reference).toBe('MOCK-142')
  })
})

describe('applyEvent on synthetic events', () => {
  const retryWork = synthetic('failure', {
    seq: 13,
    ts: '2026-11-04T02:20:00Z',
    actor: { kind: 'user', id: 'alice', display: 'Alice' },
    summary: 'Alice retried the run.',
    kind: 'run_retried',
    data: { leg: 'work', attempt: 2 },
  })

  it('a retry of the work leg clears the cast, the finding, the ticket and the approval, and starts again', () => {
    const retried = fold([retryWork], failure(12))
    expect(retried.phase).toEqual({ name: 'working' })
    expect(retried.attempt).toBe(2)
    expect(retried.agents).toEqual([])
    expect(retried.work).toEqual({ at: 'start' })
    expect([retried.finding, retried.ticket, retried.approval]).toEqual([null, null, null])
    const again = fold(renumber(slice('success', 4, 17), 14), retried)
    expect(again.agents.map((seat) => [seat.id, seat.status])).toEqual([
      [ROOM_LEAD, 'present'],
      [CHECKER, 'done'],
    ])
    expect(openStep(again)?.index).toBe(0)
  })

  it('a retry of the act leg keeps the approval and returns the work to the first write not done', () => {
    const proposal = synthetic('success', {
      seq: 12,
      ts: '2026-11-03T02:14:05.844Z',
      actor: { kind: 'agent', id: 'room_lead', display: 'Room lead' },
      summary: 'The agents proposed 2 write actions.',
      kind: 'write_action_proposed',
      data: {
        proposal_id: 'prp_x',
        digest: 'sha256:x',
        actions: [
          { connector: 'confluence', operation: 'update_page', line: 'Update Confluence page: Releases' },
          { connector: 'jira', operation: 'create_ticket', line: 'Create Jira ticket in MOCK: Releases' },
        ],
      },
    })
    const requested = synthetic('success', {
      seq: 13,
      ts: '2026-11-03T02:14:08Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'Approval requested.',
      kind: 'approval_requested',
      data: { approval_id: 'apr_x', link: '/approvals/apr_x', steps: [{ index: 0, label: 'Team approver', status: 'open', decided_by: null, decided_at: null }] },
    })
    const approved = synthetic('success', {
      seq: 14,
      ts: '2026-11-03T02:20:00Z',
      actor: { kind: 'user', id: 'bob', display: 'Bob' },
      summary: 'Bob approved the request (Team approver).',
      kind: 'approval_decided',
      data: { approval_id: 'apr_x', step: 0, verdict: 'approve', by: 'bob' },
    })
    const written = synthetic('success', {
      seq: 15,
      ts: '2026-11-03T02:20:05Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'Confluence page PAGE-7 was updated.',
      kind: 'write_action_done',
      data: { connector: 'confluence', operation: 'update_page', external_reference: 'PAGE-7', approved_by: ['bob'] },
    })
    const failed = synthetic('success', {
      seq: 16,
      ts: '2026-11-03T02:20:06Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run failed while writing.',
      kind: 'run_failed',
      data: { stage: 'acting', reason: 'WriteFailed', retryable: true, message: 'Jira did not answer' },
    })
    const retryAct = synthetic('success', {
      seq: 17,
      ts: '2026-11-03T02:21:00Z',
      actor: { kind: 'user', id: 'alice', display: 'Alice' },
      summary: 'Alice retried the run.',
      kind: 'run_retried',
      data: { leg: 'act', attempt: 2 },
    })
    const beforeRetry = fold([proposal, requested, approved, written, failed], success(11))
    expect(beforeRetry.work, 'the run failed at the Jira write').toEqual({ at: 'write', connector: JIRA })
    const resumed = fold([retryAct], beforeRetry)
    expect(resumed.phase).toEqual({ name: 'acting' })
    expect(resumed.attempt).toBe(2)
    expect(resumed.approval?.steps[0]?.state).toMatchObject({ is: 'approved', by: { id: 'bob' } })
    expect(resumed.ticket?.lines.map((line) => [line.connector, line.reference])).toEqual([
      [CONFLUENCE, 'PAGE-7'],
      [JIRA, null],
    ])
    expect(resumed.work).toEqual({ at: 'write', connector: JIRA })
  })

  it('a denied write stops at that write, and a retry of the act leg clears the denial', () => {
    const denied = synthetic('success', {
      seq: 21,
      ts: '2026-11-03T02:20:26Z',
      actor: { kind: 'safety_checker', id: 'safety_checker', display: 'Safety checker' },
      summary: 'The safety checker blocked the write: the digest did not match.',
      kind: 'write_action_denied',
      data: { reason: 'digest_mismatch', detail: 'digest mismatch' },
    })
    const blocked = fold([denied], success(20))
    expect(blocked.ticket?.denied).toEqual({ reason: 'digest_mismatch', detail: 'digest mismatch' })
    expect(blocked.work).toEqual({ at: 'write', connector: JIRA })
    const retryAct = synthetic('success', {
      seq: 22,
      ts: '2026-11-03T02:21:00Z',
      actor: { kind: 'user', id: 'alice', display: 'Alice' },
      summary: 'Alice retried the run.',
      kind: 'run_retried',
      data: { leg: 'act', attempt: 2 },
    })
    const resumed = fold([retryAct], blocked)
    expect(resumed.ticket?.denied).toBeNull()
    expect(resumed.approval?.steps[0]?.state.is).toBe('approved')
  })

  it('a failure while the proposal is prepared leaves the work at the draft', () => {
    const failed = synthetic('success', {
      seq: 13,
      ts: '2026-11-03T02:14:06Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run failed while the request was prepared.',
      kind: 'run_failed',
      data: { stage: 'proposed', reason: 'UnboundIntent', retryable: false, message: 'no allowed action' },
    })
    expect(fold([failed], success(12)).work).toEqual({ at: 'draft' })
  })

  it('opens step 1 when step 0 is approved, restarting the waiting counter', () => {
    const requested = synthetic('success', {
      seq: 15,
      ts: '2026-11-03T02:14:08.244Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'Approval requested. Waiting for the Team approver.',
      kind: 'approval_requested',
      data: {
        approval_id: 'apr_x',
        link: '/approvals/apr_x',
        steps: [
          { index: 0, label: 'Team approver', status: 'open', decided_by: null, decided_at: null },
          { index: 1, label: 'Manager', status: 'waiting', decided_by: null, decided_at: null },
        ],
      },
    })
    const bob = synthetic('success', {
      seq: 16,
      ts: '2026-11-03T02:20:00Z',
      actor: { kind: 'user', id: 'bob', display: 'Bob' },
      summary: 'Bob approved the request (Team approver).',
      kind: 'approval_decided',
      data: { approval_id: 'apr_x', step: 0, verdict: 'approve', by: 'bob' },
    })
    const dave = synthetic('success', {
      seq: 17,
      ts: '2026-11-03T02:30:00Z',
      actor: { kind: 'user', id: 'dave', display: 'Dave' },
      summary: 'Dave approved step 1 (Manager).',
      kind: 'approval_decided',
      data: { approval_id: 'apr_x', step: 1, verdict: 'approve', by: 'dave' },
    })
    const afterBob = fold([requested, bob], success(14))
    expect(afterBob.phase.name).toBe('awaiting_approval')
    expect(afterBob.work).toEqual({ at: 'gate' })
    expect(openStep(afterBob)).toMatchObject({ index: 1, state: { is: 'open', since: Date.parse('2026-11-03T02:20:00Z') } })
    const afterDave = fold([dave], afterBob)
    expect(afterDave.phase.name).toBe('acting')
    expect(afterDave.work).toEqual({ at: 'write', connector: JIRA })
    expect(afterDave.approval?.steps.map((step) => step.state)).toMatchObject([
      { is: 'approved', by: { id: 'bob', display: 'Bob' } },
      { is: 'approved', by: { id: 'dave', display: 'Dave' } },
    ])
  })

  it('accepts a re-sent approval_requested with updated statuses without restarting the open counter', () => {
    const resent = synthetic('success', {
      seq: 18,
      ts: '2026-11-03T02:16:00Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'Approval requested. Waiting for the Team approver.',
      kind: 'approval_requested',
      data: {
        approval_id: 'apr_01JB8',
        link: '/approvals/apr_01JB8',
        steps: [{ index: 0, label: 'Team approver', status: 'open', decided_by: null, decided_at: null }],
      },
    })
    expect(openStep(fold([resent], success(17)))?.state.since).toBe(at(15))
  })

  it('shows a failure with an enum value this Portal does not know', () => {
    const odd = synthetic('failure', {
      seq: 12,
      ts: '2026-11-04T02:14:13.031Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run failed in a new way.',
      kind: 'run_failed',
      data: { stage: 'working', reason: 'BrandNew', retryable: false, message: 'new' },
    })
    expect(fold([odd], failure(11)).phase).toMatchObject({ name: 'failed', reason: 'BrandNew', retryable: false })
  })

  it('leaves the state untouched for an unknown kind, apart from the cursor', () => {
    const paused = success(17)
    const left = synthetic('success', {
      seq: 18,
      ts: '2026-11-03T02:16:00Z',
      actor: { kind: 'agent', id: 'room_lead', display: 'Room lead' },
      summary: 'Release checker left the room.',
      kind: 'agent_left',
      data: { agent: 'release_checker' },
    })
    expect(left.kind).toBe('opaque')
    const room = fold([left], paused)
    expect({ ...room, cursor: 0 }).toEqual({ ...paused, cursor: 0 })
    expect(room.cursor).toBe(18)
  })

  it('shows nothing to write as no ticket and the work at the end', () => {
    const done = synthetic('success', {
      seq: 12,
      ts: '2026-11-03T02:14:06Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run succeeded. There was nothing to write.',
      kind: 'run_succeeded',
      data: { outcome: 'nothing_to_write' },
    })
    const room = fold([done], success(11))
    expect(room.ticket).toBeNull()
    expect(room.work).toEqual({ at: 'done' })
    expect(room.phase).toEqual({ name: 'succeeded', outcome: 'nothing_to_write' })
  })
})
