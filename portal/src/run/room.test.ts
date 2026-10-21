import { describe, expect, it } from 'vitest'
import type { BlockView } from '../api/types'
import type { RunEvent } from '../stream/parse'
import { agentId } from './brand'
import { recording, renumber, slice, synthetic } from './recordings'
import { applyEvent, EMPTY_ROOM, openStep, spineStations, type RoomState } from './room'
import { TEST_REGISTRY } from './testing'

function fold(events: readonly RunEvent[], from: RoomState = EMPTY_ROOM): { room: RoomState } {
  return { room: events.reduce((room, event) => applyEvent(room, event, TEST_REGISTRY), from) }
}

const ROOM_LEAD = agentId('room_lead')
const CHECKER = agentId('release_checker')
const TROUBLE = agentId('troubleshooter')

const BLOCKS: readonly BlockView[] = [
  { key: 'read_releases', name: 'Read GitHub releases', description: '', kind: 'agent' },
  { key: 'approval_gate', name: 'Approval gate', description: '', kind: 'approval' },
  { key: 'create_ticket', name: 'Create Jira ticket', description: '', kind: 'write_action' },
]

describe('applyEvent on the recordings', () => {
  it('seats the Room lead with the starter on run_created, before any guest', () => {
    const { room } = fold(slice('success', 1, 1))
    expect(room.phase).toEqual({ name: 'pending' })
    expect(room.starter).toEqual({ id: 'alice', display: 'Alice' })
    expect(room.agents.map((seat) => [seat.id, seat.role])).toEqual([[ROOM_LEAD, 'host']])
    expect(room.caption?.summary).toBe('Alice started a run of LangGraph releases.')
  })

  it('ends the success recording written, with the ticket carrying MOCK-142', () => {
    const { room } = fold(recording('success'))
    expect(room.phase).toEqual({ name: 'succeeded', outcome: 'written' })
    expect(room.ticket?.lines[0]?.reference).toBe('MOCK-142')
    expect(room.approval?.steps[0]?.state).toMatchObject({ is: 'approved', by: { id: 'bob', display: 'Bob' } })
    expect(room.agents.map((seat) => seat.id)).toEqual([ROOM_LEAD, CHECKER])
    expect(room.caption?.summary).toBe('The run succeeded. 1 write action was done.')
    expect(room.speech).toBeNull()
  })

  it('waits at the pause with the open step and the Teams post', () => {
    const { room } = fold(slice('success', 1, 17))
    const open = openStep(room)
    expect(open?.index).toBe(0)
    expect(open?.label).toBe('Team approver')
    expect(open?.state.since).toBe(Date.parse('2026-11-03T02:14:08.244Z'))
    expect(room.approval?.teams).toEqual({ is: 'posted', channel: 'CODESparks Ops' })
    expect(room.speech).toBeNull()
  })

  it('puts only agent_message text in an agent mouth and the latest captioned story summary in the caption', () => {
    const { room } = fold(slice('success', 1, 5))
    expect(room.speech?.text).toBe(
      'Please check langchain-ai/langgraph for releases newer than 1.2.14.',
    )
    expect(room.speech?.speaker).toBe(ROOM_LEAD)
    expect(room.speech?.to).toEqual({ kind: 'agent', id: CHECKER, display: 'Release checker' })
    expect(fold(slice('success', 1, 9)).room.caption?.summary).toBe('Release checker found 2 new releases: 1.2.16, 1.2.15.')
    expect(fold(slice('success', 1, 4)).room.speech).toBeNull()
  })

  it('keeps a step start out of the caption, so the ask stays up while the step runs', () => {
    const asked = fold(slice('success', 1, 5)).room
    const fetching = fold(slice('success', 1, 6)).room
    expect(fetching.caption).toEqual(asked.caption)
    expect(fold(slice('success', 1, 7)).room.caption?.summary).toBe('Release checker fetched 30 releases. The latest is 1.2.16.')
  })

  it('clears speech when a step starts or finishes, when the phase changes, and otherwise keeps it', () => {
    expect(fold(slice('success', 1, 5)).room.speech?.speaker).toBe(ROOM_LEAD)
    expect(fold(slice('success', 1, 6)).room.speech).toBeNull()
    expect(fold(slice('success', 1, 10)).room.speech?.speaker).toBe(CHECKER)
    const afterProposal = fold(slice('success', 1, 12)).room
    expect(afterProposal.phase.name).toBe('proposed')
    expect(afterProposal.speech).toBeNull()
    const third = fold(slice('failure', 1, 9)).room
    expect(third.speech?.text).toMatch(/^GitHub answered 503 Service Unavailable \(try 3/)
    expect(fold(slice('failure', 1, 10)).room.speech, 'the agent failing keeps its last words up').toEqual(third.speech)
    expect(fold(slice('failure', 1, 12)).room.speech, 'the run failing clears them').toBeNull()
  })

  it.each(['success', 'failure', 'rejected'] as const)('%s: plumbing changes nothing visible', (name) => {
    const events = recording(name)
    const withoutPlumbing = events.filter(
      (event) => !['leg_dispatched', 'step_started', 'step_finished', 'step_retried'].includes(event.kind),
    )
    for (let to = 1; to <= events.length; to += 1) {
      const full = fold(events.filter((event) => event.seq <= to)).room
      const lean = fold(withoutPlumbing.filter((event) => event.seq <= to)).room
      expect({ ...full, cursor: 0 }).toEqual({ ...lean, cursor: 0 })
    }
  })

  it('keeps a finding when a step returns a list, through the talk, until the proposal', () => {
    expect(fold(slice('success', 1, 7)).room.finding, 'a count and a version are not a finding').toBeNull()
    const found = fold(slice('success', 1, 9)).room
    expect(found.finding).toEqual({ agent: CHECKER, step: 'find_new', items: ['1.2.16', '1.2.15'] })
    expect(fold(slice('success', 1, 11)).room.finding).toEqual(found.finding)
    expect(fold(slice('success', 1, 12)).room.finding).toBeNull()
    expect(fold(slice('success', 1, 12)).room.ticket).not.toBeNull()
  })

  it('stops the agent that failed and seats the troubleshooter when the run fails', () => {
    const failed = fold(slice('failure', 1, 12))
    expect(failed.room.agents[1]?.status).toBe('stopped')
    expect(failed.room.phase).toMatchObject({ name: 'failed', reason: 'AgentError', retryable: true, stage: 'working' })
    expect(failed.room.agents.map((seat) => [seat.id, seat.role])).toEqual([
      [ROOM_LEAD, 'host'],
      [CHECKER, 'specialist'],
      [TROUBLE, 'troubleshooter'],
    ])
  })

  it('ends a rejection declined by Bob with nothing written', () => {
    const { room } = fold(recording('rejected'))
    expect(room.phase).toEqual({ name: 'rejected', by: { id: 'bob', display: 'Bob' }, step: 0 })
    expect(room.approval?.steps[0]?.state).toMatchObject({ is: 'declined', by: { id: 'bob', display: 'Bob' } })
    expect(room.ticket?.lines.every((line) => line.reference === null)).toBe(true)
  })

  it('acts once the approver says yes, then records the reference written', () => {
    const decided = fold(slice('success', 1, 18))
    expect(decided.room.phase.name).toBe('acting')
    expect(openStep(decided.room)).toBeNull()
    expect(decided.room.ticket?.lines[0]?.reference).toBeNull()
    const written = fold(slice('success', 1, 21))
    expect(written.room.ticket?.lines[0]?.reference).toBe('MOCK-142')
  })
})

describe('applyEvent on synthetic events', () => {
  const failed = fold(slice('failure', 1, 12)).room
  const retried = synthetic('failure', {
    seq: 13,
    ts: '2026-11-04T02:20:00Z',
    actor: { kind: 'user', id: 'alice', display: 'Alice' },
    summary: 'Alice retried the run.',
    kind: 'run_retried',
    data: { leg: 'work', attempt: 2 },
  })

  it('retry walks the troubleshooter out and keeps the join order on re-join', () => {
    const afterRetry = fold([retried], failed)
    expect(afterRetry.room.phase).toEqual({ name: 'working' })
    expect(afterRetry.room.attempt).toBe(2)
    expect(afterRetry.room.agents.map((seat) => [seat.id, seat.status])).toEqual([
      [ROOM_LEAD, 'present'],
      [CHECKER, 'present'],
    ])
    const secondWork = renumber(
      slice('success', 4, 17).map((event) => ({ ...event, actor: event.actor })),
      14,
    )
    const again = fold(secondWork, afterRetry.room).room
    expect(again.agents.map((seat) => seat.id)).toEqual([ROOM_LEAD, CHECKER])
    expect(openStep(again)?.index).toBe(0)
  })

  it('a retry of the work leg clears the finding', () => {
    const found = fold(slice('success', 1, 9)).room
    const retryWork = synthetic('success', {
      seq: 10,
      ts: '2026-11-03T02:15:00Z',
      actor: { kind: 'user', id: 'alice', display: 'Alice' },
      summary: 'Alice retried the run.',
      kind: 'run_retried',
      data: { leg: 'work', attempt: 2 },
    })
    expect(fold([retryWork], found).room.finding).toBeNull()
  })

  it('retry of the act leg keeps the ticket and clears the denial', () => {
    const acting = fold(slice('success', 1, 20)).room
    const denied = synthetic('success', {
      seq: 21,
      ts: '2026-11-03T02:20:26Z',
      actor: { kind: 'safety_checker', id: 'safety_checker', display: 'Safety checker' },
      summary: 'The safety checker blocked the write: the digest did not match.',
      kind: 'write_action_denied',
      data: { reason: 'digest_mismatch', detail: 'digest mismatch' },
    })
    const blocked = fold([denied], acting)
    expect(blocked.room.ticket?.denied).toEqual({ reason: 'digest_mismatch', detail: 'digest mismatch' })
    const retryAct = synthetic('success', {
      seq: 22,
      ts: '2026-11-03T02:21:00Z',
      actor: { kind: 'user', id: 'alice', display: 'Alice' },
      summary: 'Alice retried the run.',
      kind: 'run_retried',
      data: { leg: 'act', attempt: 2 },
    })
    const resumed = fold([retryAct], blocked.room).room
    expect(resumed.phase).toEqual({ name: 'acting' })
    expect(resumed.ticket?.denied).toBeNull()
    expect(resumed.approval?.steps[0]?.state.is).toBe('approved')
  })

  it('opens step 1 when step 0 is approved, restarting the waiting counter', () => {
    const before = fold(slice('success', 1, 14)).room
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
    const afterBob = fold([requested, bob], before).room
    expect(afterBob.phase.name).toBe('awaiting_approval')
    expect(openStep(afterBob)).toMatchObject({ index: 1, state: { is: 'open', since: Date.parse('2026-11-03T02:20:00Z') } })
    const afterDave = fold([dave], afterBob).room
    expect(afterDave.phase.name).toBe('acting')
    expect(afterDave.approval?.steps.map((step) => step.state.is)).toEqual(['approved', 'approved'])
    expect(spineStations(afterDave, BLOCKS)[1]?.state).toEqual({
      is: 'approved',
      by: [
        { id: 'bob', display: 'Bob' },
        { id: 'dave', display: 'Dave' },
      ],
    })
  })

  it('accepts a re-sent approval_requested with updated statuses without restarting the open counter', () => {
    const paused = fold(slice('success', 1, 17)).room
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
    const again = fold([resent], paused).room
    expect(openStep(again)?.state.since).toBe(Date.parse('2026-11-03T02:14:08.244Z'))
  })

  it('shows a failure with an enum value this Portal does not know', () => {
    const working = fold(slice('failure', 1, 11)).room
    const odd = synthetic('failure', {
      seq: 12,
      ts: '2026-11-04T02:14:13.031Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run failed in a new way.',
      kind: 'run_failed',
      data: { stage: 'working', reason: 'BrandNew', retryable: false, message: 'new' },
    })
    const room = fold([odd], working).room
    expect(room.phase).toMatchObject({ name: 'failed', reason: 'BrandNew', retryable: false })
  })

  it('leaves the room untouched for an unknown kind, apart from the cursor', () => {
    const paused = fold(slice('success', 1, 17)).room
    const left = synthetic('success', {
      seq: 18,
      ts: '2026-11-03T02:16:00Z',
      actor: { kind: 'agent', id: 'room_lead', display: 'Room lead' },
      summary: 'Release checker left the room.',
      kind: 'agent_left',
      data: { agent: 'release_checker' },
    })
    expect(left.kind).toBe('opaque')
    const { room } = fold([left], paused)
    expect({ ...room, cursor: 0 }).toEqual({ ...paused, cursor: 0 })
    expect(room.cursor).toBe(18)
  })

  it('shows nothing to write as no ticket and not-needed blocks', () => {
    const working = fold(slice('success', 1, 11)).room
    const done = synthetic('success', {
      seq: 12,
      ts: '2026-11-03T02:14:06Z',
      actor: { kind: 'platform', id: 'platform', display: 'Platform' },
      summary: 'The run succeeded. There was nothing to write.',
      kind: 'run_succeeded',
      data: { outcome: 'nothing_to_write' },
    })
    const room = fold([done], working).room
    expect(room.ticket).toBeNull()
    expect(spineStations(room, BLOCKS).map((station) => station.state.is)).toEqual(['done', 'not_needed', 'not_needed'])
  })
})

describe('spineStations', () => {
  it('follows the recordings', () => {
    const states = (events: readonly RunEvent[]) => spineStations(fold(events).room, BLOCKS).map((s) => s.state.is)
    expect(states(slice('success', 1, 1))).toEqual(['not_reached', 'not_reached', 'not_reached'])
    expect(states(slice('success', 1, 6))).toEqual(['working', 'not_reached', 'not_reached'])
    expect(states(slice('success', 1, 12))).toEqual(['done', 'not_reached', 'not_reached'])
    expect(states(slice('success', 1, 17))).toEqual(['done', 'waiting', 'not_reached'])
    expect(states(slice('success', 1, 18))).toEqual(['done', 'approved', 'working'])
    expect(states(slice('success', 1, 20))).toEqual(['done', 'approved', 'working'])
    expect(states(recording('success'))).toEqual(['done', 'approved', 'done'])
    expect(states(recording('failure'))).toEqual(['failed', 'not_reached', 'not_reached'])
    expect(states(recording('rejected'))).toEqual(['done', 'declined', 'not_reached'])
  })

  it('carries the waiting since and the decider', () => {
    const paused = spineStations(fold(slice('success', 1, 17)).room, BLOCKS)
    expect(paused[1]?.state).toEqual({ is: 'waiting', since: Date.parse('2026-11-03T02:14:08.244Z') })
    const declined = spineStations(fold(recording('rejected')).room, BLOCKS)
    expect(declined[1]?.state).toEqual({ is: 'declined', by: { id: 'bob', display: 'Bob' } })
  })
})
