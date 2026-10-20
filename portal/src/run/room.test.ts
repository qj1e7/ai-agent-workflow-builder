import { describe, expect, it } from 'vitest'
import type { BlockView } from '../api/types'
import type { RunEvent } from '../stream/parse'
import { agentId, doorKey } from './brand'
import { recording, renumber, slice, synthetic } from './recordings'
import {
  applyEvent,
  EMPTY_ROOM,
  floorPlanOf,
  openStep,
  spineStations,
  ticketLife,
  type Move,
  type RoomState,
} from './room'
import { TEST_REGISTRY } from './testing'

function fold(events: readonly RunEvent[], from: RoomState = EMPTY_ROOM): { room: RoomState; moves: (Move | null)[] } {
  const moves: (Move | null)[] = []
  let room = from
  for (const event of events) {
    const next = applyEvent(room, event, TEST_REGISTRY)
    room = next.room
    moves.push(next.move)
  }
  return { room, moves }
}

const ROOM_LEAD = agentId('room_lead')
const CHECKER = agentId('release_checker')
const TROUBLE = agentId('troubleshooter')
const JIRA = doorKey('jira')
const GITHUB = doorKey('github')

const BLOCKS: readonly BlockView[] = [
  { key: 'read_releases', name: 'Read GitHub releases', description: '', kind: 'agent' },
  { key: 'approval_gate', name: 'Approval gate', description: '', kind: 'approval' },
  { key: 'create_ticket', name: 'Create Jira ticket', description: '', kind: 'write_action' },
]

function writeDoor(room: RoomState, key = JIRA) {
  const door = room.doors.find((candidate) => candidate.side === 'write' && candidate.key === key)
  if (!door || door.side !== 'write') throw new Error(`no write door ${key}`)
  return door
}

describe('applyEvent on the recordings', () => {
  it('seats the Room lead with the starter on run_created, before any guest', () => {
    const { room, moves } = fold(slice('success', 1, 1))
    expect(room.phase).toEqual({ name: 'pending' })
    expect(room.starter).toEqual({ id: 'alice', display: 'Alice' })
    expect(room.agents.map((seat) => [seat.id, seat.slot, seat.role])).toEqual([[ROOM_LEAD, 0, 'host']])
    expect(room.doors).toEqual([{ side: 'teams' }])
    expect(moves[0]).toEqual({ type: 'open_room' })
    expect(room.caption?.summary).toBe('Alice started a run of LangGraph releases.')
  })

  it('ends the success recording written, with the ticket carrying MOCK-142', () => {
    const { room } = fold(recording('success'))
    expect(room.phase).toEqual({ name: 'succeeded', outcome: 'written' })
    expect(room.ticket?.lines[0]?.reference).toBe('MOCK-142')
    expect(ticketLife(room)).toBe('written')
    expect(room.approval?.steps[0]?.state).toMatchObject({ is: 'approved', by: { id: 'bob', display: 'Bob' } })
    expect(writeDoor(room).checker).toBe('allowed')
    expect(room.agents.map((seat) => [seat.id, seat.slot])).toEqual([
      [ROOM_LEAD, 0],
      [CHECKER, 1],
    ])
    expect(room.caption?.summary).toBe('The run succeeded. 1 write action was done.')
    expect(room.speech).toBeNull()
  })

  it('waits at the pause with the open step, the Teams post and the amber light on the empty seat', () => {
    const { room } = fold(slice('success', 1, 17))
    const open = openStep(room)
    expect(open?.index).toBe(0)
    expect(open?.label).toBe('Team approver')
    expect(open?.state.since).toBe(Date.parse('2026-11-03T02:14:08.244Z'))
    expect(room.approval?.teams).toEqual({ is: 'posted', channel: 'CODESparks Ops' })
    expect(room.light).toEqual({ on: { at: 'step', index: 0 }, tone: 'wait' })
    expect(ticketLife(room)).toBe('waiting')
    expect(room.speech).toBeNull()
    expect(writeDoor(room).checker).toBe('locked')
  })

  it('puts only agent_message text in an agent mouth and the latest story summary in the caption', () => {
    const { room } = fold(slice('success', 1, 9))
    expect(room.speech?.text).toBe(
      'Please check langchain-ai/langgraph for releases newer than 1.2.14.',
    )
    expect(room.speech?.speaker).toBe(ROOM_LEAD)
    expect(room.speech?.to).toEqual({ kind: 'agent', id: CHECKER, display: 'Release checker' })
    expect(room.caption?.summary).toBe('Release checker found 2 new releases: 1.2.16, 1.2.15.')
    expect(fold(slice('success', 1, 4)).room.speech).toBeNull()
  })

  it('keeps speech through a step change but clears it when the phase changes', () => {
    const afterMessage = fold(slice('success', 1, 10)).room
    expect(afterMessage.speech?.speaker).toBe(CHECKER)
    const afterProposal = fold(slice('success', 1, 12)).room
    expect(afterProposal.phase.name).toBe('proposed')
    expect(afterProposal.speech).toBeNull()
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

  it('sends a request out of the GitHub door and brings it back', () => {
    const out = fold(slice('success', 1, 6))
    expect(out.room.trips).toEqual([{ agent: CHECKER, step: 'fetch_releases', door: GITHUB, marks: 0, state: 'out' }])
    expect(out.moves.at(-1)).toEqual({
      type: 'carry',
      token: 'request',
      from: { at: 'agent', id: CHECKER },
      to: { at: 'door', key: GITHUB },
    })
    expect(out.room.doors).toContainEqual({ side: 'read', key: GITHUB })
    expect(out.room.agents[1]?.status).toBe('working')
    const back = fold(slice('success', 1, 7))
    expect(back.room.trips[0]?.state).toBe('back')
    expect(back.room.agents[1]?.status).toBe('done')
    expect(back.moves.at(-1)).toEqual({
      type: 'carry',
      token: 'request',
      from: { at: 'door', key: GITHUB },
      to: { at: 'agent', id: CHECKER },
    })
  })

  it('numbers the messages sent during an open trip, then turns the trip red on failure', () => {
    const marked = fold(slice('failure', 1, 9))
    expect(marked.room.trips[0]).toMatchObject({ state: 'out', marks: 3 })
    expect(marked.moves.at(-1)).toEqual({
      type: 'speak',
      who: { at: 'agent', id: CHECKER },
      mark: { agent: CHECKER, step: 'fetch_releases', n: 3 },
    })
    const failed = fold(slice('failure', 1, 12))
    expect(failed.room.trips[0]?.state).toBe('failed')
    expect(failed.room.agents[1]?.status).toBe('stopped')
    expect(failed.room.phase).toMatchObject({ name: 'failed', reason: 'AgentError', retryable: true, stage: 'working' })
    expect(failed.room.agents.map((seat) => [seat.id, seat.slot, seat.role])).toEqual([
      [ROOM_LEAD, 0, 'host'],
      [CHECKER, 1, 'specialist'],
      [TROUBLE, 2, 'troubleshooter'],
    ])
    expect(failed.moves.at(-1)).toEqual({ type: 'arrive', who: { at: 'agent', id: TROUBLE } })
    expect(failed.room.light).toEqual({ on: { at: 'agent', id: TROUBLE }, tone: 'act' })
    expect(fold(slice('failure', 1, 10)).moves.at(-1)).toEqual({ type: 'fault', at: { at: 'door', key: GITHUB } })
  })

  it('ends a rejection with the ticket declined at the edge of the table and the Jira door locked', () => {
    const { room, moves } = fold(recording('rejected'))
    expect(room.phase).toEqual({ name: 'rejected', by: { id: 'bob', display: 'Bob' }, step: 0 })
    expect(ticketLife(room)).toBe('declined')
    expect(writeDoor(room).checker).toBe('locked')
    expect(moves.at(-1)).toEqual({ type: 'carry', token: 'ticket', from: { at: 'table' }, to: { at: 'table_edge' } })
    expect(moves.at(-2)).toEqual({ type: 'decide', step: 0, verdict: 'decline' })
  })

  it('walks the approver in and stamps the ticket, then lets the write through the door', () => {
    const decided = fold(slice('success', 1, 18))
    expect(decided.moves.at(-1)).toEqual({ type: 'decide', step: 0, verdict: 'approve' })
    expect(decided.room.phase.name).toBe('acting')
    expect(openStep(decided.room)).toBeNull()
    expect(ticketLife(decided.room)).toBe('approved')
    const written = fold(slice('success', 1, 21))
    expect(written.moves.at(-1)).toEqual({ type: 'deliver', door: JIRA, reference: 'MOCK-142' })
    expect(writeDoor(written.room).checker).toBe('allowed')
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

  it('retry clears the marks, walks the troubleshooter out and keeps slots on re-join', () => {
    const afterRetry = fold([retried], failed)
    expect(afterRetry.moves[0]).toEqual({ type: 'leave', who: { at: 'agent', id: TROUBLE } })
    expect(afterRetry.room.phase).toEqual({ name: 'working' })
    expect(afterRetry.room.attempt).toBe(2)
    expect(afterRetry.room.trips).toEqual([])
    expect(afterRetry.room.agents.map((seat) => [seat.id, seat.status])).toEqual([
      [ROOM_LEAD, 'present'],
      [CHECKER, 'present'],
    ])
    const secondWork = renumber(
      slice('success', 4, 17).map((event) => ({ ...event, actor: event.actor })),
      14,
    )
    const again = fold(secondWork, afterRetry.room).room
    expect(again.agents.map((seat) => [seat.id, seat.slot])).toEqual([
      [ROOM_LEAD, 0],
      [CHECKER, 1],
    ])
    expect(openStep(again)?.index).toBe(0)
  })

  it('retry of the act leg keeps the ticket and locks the doors again', () => {
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
    expect(writeDoor(blocked.room).checker).toBe('blocked')
    expect(ticketLife(blocked.room)).toBe('denied')
    expect(blocked.moves[0]).toEqual({ type: 'fault', at: { at: 'door', key: JIRA } })
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
    expect(writeDoor(resumed).checker).toBe('locked')
    expect(ticketLife(resumed)).toBe('approved')
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
    expect(afterBob.light).toEqual({ on: { at: 'step', index: 1 }, tone: 'wait' })
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
    const { room, moves } = fold([left], paused)
    expect(moves[0]).toBeNull()
    expect({ ...room, cursor: 0 }).toEqual({ ...paused, cursor: 0 })
    expect(room.cursor).toBe(18)
  })

  it('shows nothing to write as an empty table and not-needed blocks', () => {
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

describe('floorPlanOf', () => {
  it('lists seats by slot, doors by wall, and seeds write doors from the template until a proposal names them', () => {
    const early = floorPlanOf(fold(slice('success', 1, 6)).room, [{ label: 'Create a ticket', key: null }])
    expect(early.agents).toEqual([
      { key: 'agent:room_lead', slot: 0 },
      { key: 'agent:release_checker', slot: 1 },
    ])
    expect(early.people).toEqual([{ key: 'starter', slot: 0 }])
    expect(early.doors).toEqual([
      { side: 'teams', key: 'teams', label: null },
      { side: 'read', key: GITHUB, label: null },
      { side: 'write', key: null, label: 'Create a ticket' },
    ])
    const proposed = floorPlanOf(fold(slice('success', 1, 17)).room, [{ label: 'Create a ticket', key: null }])
    expect(proposed.doors).toContainEqual({ side: 'write', key: JIRA, label: 'Create a ticket' })
    expect(proposed.doors.filter((door) => door.side === 'write')).toHaveLength(1)
    expect(proposed.people).toEqual([
      { key: 'starter', slot: 0 },
      { key: 'step:0', slot: 1 },
    ])
  })

  it('names a seeded write door after the connector its block names, from the first frame', () => {
    const seed = [{ label: 'Create Jira ticket', key: JIRA }]
    const early = floorPlanOf(fold(slice('success', 1, 6)).room, seed)
    expect(early.doors).toContainEqual({ side: 'write', key: JIRA, label: 'Create Jira ticket' })
    const proposed = floorPlanOf(fold(slice('success', 1, 17)).room, seed)
    expect(proposed.doors.filter((door) => door.side === 'write')).toEqual([{ side: 'write', key: JIRA, label: 'Create Jira ticket' }])
  })
})
