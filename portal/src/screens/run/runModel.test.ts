import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { describe, expect, it } from 'vitest'
import type { BlockKind } from '../../api/types'
import { runId } from '../../stream/brand'
import { parseEvent, type RunEvent } from '../../stream/parse'
import { emptyModel, fold, foldAll, reachOf, stationsOf, type PlanBlock, type RunModel, type Station } from './runModel'

interface Raw {
  readonly run_id: string
  readonly seq: number
}

function parsed(raw: readonly Raw[]): RunEvent[] {
  return raw.map((item) => {
    const result = parseEvent(item, runId(item.run_id))
    if (!result.ok) throw new Error(result.problem)
    return result.event
  })
}

const replay = (raw: readonly Raw[], upTo = Infinity): RunModel => foldAll(emptyModel, parsed(raw.filter((item) => item.seq <= upTo)))

const PLAN: PlanBlock[] = useCase.plan.map((block) => ({ name: block.name, kind: block.kind as BlockKind }))
const writeLabel = () => 'Write in Jira'

const shape = (stations: readonly Station[]) => stations.map((s) => `${s.key}:${s.state}:${s.face}`)

function event(seq: number, kind: string, data: Record<string, unknown>, actor = { kind: 'platform', id: 'platform', display: 'Platform' }): RunEvent {
  const result = parseEvent({ run_id: 'run_01JB9', seq, ts: '2026-11-04T02:20:00Z', actor, summary: '', kind, data }, runId('run_01JB9'))
  if (!result.ok) throw new Error(result.problem)
  return result.event
}

describe('a run that was approved and wrote its ticket', () => {
  const model = replay(success)

  it('ends succeeded, with what it wrote and who approved it', () => {
    expect(model.seq).toBe(success.length)
    expect(model.phase).toEqual({ state: 'succeeded', outcome: 'written' })
    expect(model.written.map((w) => [w.connector, w.operation])).toEqual([['jira', 'create_ticket']])
    expect(model.written.map((w) => w.ref)).toEqual(['MOCK-142'])
    expect(model.approvedBy).toEqual(['bob'])
    expect(model.startedBy).toBe('alice')
    expect(model.people).toMatchObject({ alice: 'Alice', bob: 'Bob' })
    expect(model.approvalId).toBe('apr_01JB8')
  })

  it('marks every step done and the agent that did the work happy', () => {
    expect(shape(stationsOf(model, PLAN, writeLabel))).toEqual([
      'started:done:idle',
      'planner:done:idle',
      'agent:0:done:success',
      'gate:done:idle',
      'write:done:idle',
      'done:done:idle',
    ])
    expect(reachOf(stationsOf(model, PLAN, writeLabel))).toBe(1)
  })

  it('names the steps from the plan and the agent under its step', () => {
    const stations = stationsOf(model, PLAN, writeLabel)
    expect(stations.map((s) => s.label)).toEqual(['Started', 'Pick agents', 'Read every source', 'Approval gate', 'Create Jira tickets', 'Done'])
    expect(stations[2]?.sub).toBe('Version checker')
    expect(stations[2]?.who).toEqual({ kind: 'agent', agent: { id: 'version_checker', display: 'Version checker' } })
    expect(stations[0]?.who).toEqual({ kind: 'person', id: 'alice' })
  })

  it('draws the same line without a plan, naming steps after their agents', () => {
    const stations = stationsOf(model, null, writeLabel)
    expect(stations.map((s) => s.label)).toEqual(['Started', 'Pick agents', 'Version checker', 'Approval gate', 'Write in Jira', 'Done'])
  })

  it('tells the run as a chat, with no workflow plumbing in it', () => {
    expect(model.chat.map((item) => item.kind)).toEqual(['started', 'joined', 'said', 'said', 'said', 'asked', 'decided', 'written', 'finished'])
    const asked = model.chat.find((item) => item.kind === 'asked')
    expect(asked).toMatchObject({ channel: 'CODESparks Ops', posted: true })
    expect(model.chat.find((item) => item.kind === 'decided')).toMatchObject({ by: 'bob', verdict: 'approve', step: null })
    expect(model.chat.find((item) => item.kind === 'finished')).toMatchObject({ outcome: 'written', count: 1, operation: 'create_ticket' })
    for (const item of model.chat) if (item.kind === 'said') expect(item.text).not.toMatch(/n8n|execution/i)
  })
})

describe('the same run part way', () => {
  it('while the Version checker reads, has the Planner done and the checker working', () => {
    const model = replay(success, 6)
    expect(model.phase.state).toBe('working')
    expect(shape(stationsOf(model, PLAN, writeLabel))).toEqual([
      'started:done:idle',
      'planner:done:idle',
      'agent:0:now:working',
      'gate:todo:idle',
      'write:todo:idle',
      'done:todo:idle',
    ])
  })

  it('before anyone joins, keeps the plan’s agent step in place with nobody in it yet', () => {
    const model = replay(success, 3)
    const stations = stationsOf(model, PLAN, writeLabel)
    expect(stations).toHaveLength(6)
    expect(stations[2]?.who).toEqual({ kind: 'agent', agent: null })
    expect(shape(stations)[0]).toBe('started:now:idle')
  })

  it('at the gate, waits for a yes with the agent before it waiting too', () => {
    const model = replay(success, 15)
    expect(model.phase.state).toBe('awaiting_approval')
    expect(shape(stationsOf(model, PLAN, writeLabel))).toEqual([
      'started:done:idle',
      'planner:done:idle',
      'agent:0:done:waiting',
      'gate:wait:idle',
      'write:todo:idle',
      'done:todo:idle',
    ])
    expect(reachOf(stationsOf(model, PLAN, writeLabel))).toBe(3 / 5)
  })

  it('after the yes, writes while the gate shows done', () => {
    const model = replay(success, 16)
    expect(model.phase.state).toBe('acting')
    expect(shape(stationsOf(model, PLAN, writeLabel)).slice(3)).toEqual(['gate:done:idle', 'write:now:idle', 'done:todo:idle'])
  })
})

describe('a run that was declined', () => {
  const model = replay(rejected)

  it('ends rejected, naming who declined and at which step', () => {
    expect(model.phase).toEqual({ state: 'rejected', by: 'bob', step: 0 })
    expect(model.written).toEqual([])
  })

  it('shows the gate as declined and the write as not needed', () => {
    expect(shape(stationsOf(model, PLAN, writeLabel))).toEqual([
      'started:done:idle',
      'planner:done:idle',
      'agent:0:done:idle',
      'gate:declined:idle',
      'write:skip:idle',
      'done:done:idle',
    ])
  })

  it('says who declined in the chat', () => {
    expect(model.chat.filter((item) => item.kind === 'decided' || item.kind === 'declined')).toMatchObject([
      { kind: 'decided', by: 'bob', verdict: 'decline' },
      { kind: 'declined' },
    ])
  })
})

describe('a run that failed', () => {
  const model = replay(failure)

  it('ends failed with the stage, reason and whether it can be retried', () => {
    expect(model.phase).toMatchObject({ state: 'failed', stage: 'working', reason: 'AgentError', retryable: true })
  })

  it('marks the agent that stopped and leaves the rest not reached', () => {
    expect(shape(stationsOf(model, PLAN, writeLabel))).toEqual([
      'started:done:idle',
      'planner:done:idle',
      'agent:0:fail:error',
      'gate:todo:idle',
      'write:todo:idle',
      'done:todo:idle',
    ])
    expect(reachOf(stationsOf(model, PLAN, writeLabel))).toBe(2 / 5)
  })

  it('lets the agent say what went wrong, and ends the chat with the stop', () => {
    const bad = model.chat.filter((item) => item.kind === 'said' && item.bad)
    expect(bad).toHaveLength(1)
    expect(bad[0]).toMatchObject({ speaker: { id: 'version_checker' } })
    expect(model.chat.at(-1)).toMatchObject({ kind: 'stopped', stage: 'working' })
  })

  it('marks the Planner when a run fails before any agent starts', () => {
    const early = foldAll(emptyModel, [
      ...parsed(failure.slice(0, 2)),
      event(3, 'run_failed', { stage: 'pending', reason: 'DispatchFailed', retryable: true, message: 'n8n is down' }),
    ])
    expect(shape(stationsOf(early, PLAN, writeLabel)).slice(0, 3)).toEqual(['started:done:idle', 'planner:fail:error', 'agent:0:todo:idle'])
  })
})

describe('a retry', () => {
  const alice = { kind: 'user', id: 'alice', display: 'Alice' }
  const failed = replay(failure)
  const retried = fold(failed, event(15, 'run_retried', { leg: 'work', attempt: 2 }, alice))

  it('starts the work again, clearing the failure and the agents', () => {
    expect(retried.phase).toEqual({ state: 'pending' })
    expect(retried.failedAt).toBeNull()
    expect(retried.agents).toEqual([])
    expect(retried.retriedBy).toEqual(['alice'])
    expect(retried.chat.at(-1)).toMatchObject({ kind: 'retried', by: 'alice' })
    expect(shape(stationsOf(retried, PLAN, writeLabel)).slice(0, 3)).toEqual(['started:now:idle', 'planner:todo:idle', 'agent:0:todo:idle'])
  })

  it('draws the second attempt as it goes', () => {
    const again = foldAll(retried, [
      event(16, 'agent_joined', { agent: { id: 'version_checker', display: 'Version checker' }, reason: 'again' }, { kind: 'agent', id: 'planner', display: 'Planner' }),
      event(17, 'agent_step_started', { step: 'read_source' }, { kind: 'agent', id: 'version_checker', display: 'Version checker' }),
    ])
    expect(again.phase.state).toBe('working')
    expect(shape(stationsOf(again, PLAN, writeLabel)).slice(0, 3)).toEqual(['started:done:idle', 'planner:done:idle', 'agent:0:now:working'])
  })

  it('after a failed write, carries on at the write without asking again', () => {
    const writeFailed = { ...failed, phase: { state: 'failed', stage: 'acting', reason: 'WriteFailed', retryable: true, message: '' } } as const
    const again = fold({ ...writeFailed, failedAt: { at: 'write' } }, event(15, 'run_retried', { leg: 'act', attempt: 2 }, alice))
    expect(again.phase).toEqual({ state: 'acting' })
    expect(again.spot).toEqual({ at: 'write' })
  })
})

describe('events out of order or repeated', () => {
  const events = parsed(success)
  const atTwo = foldAll(emptyModel, events.slice(0, 2))

  it('ignores an event that skips ahead', () => {
    const third = events[3]
    if (!third) throw new Error('no fourth event')
    expect(fold(atTwo, third)).toBe(atTwo)
  })

  it('ignores an event it already has', () => {
    const second = events[1]
    if (!second) throw new Error('no second event')
    expect(fold(atTwo, second)).toBe(atTwo)
  })

  it('folds the whole run to the same model however often the backlog repeats', () => {
    expect(foldAll(foldAll(emptyModel, events), events)).toEqual(foldAll(emptyModel, events))
  })
})

describe('kinds the page does not draw', () => {
  const base = replay(success, 2)

  it('move only the cursor for a kind from a newer platform', () => {
    const next = fold(base, event(3, 'agent_did_something_new', { anything: 1 }))
    expect(next).toEqual({ ...base, seq: 3 })
  })

  it('move only the cursor for workflow plumbing', () => {
    const next = fold(base, event(3, 'step_started', { step: 'run_agents', n8n_execution_id: '41', try_number: 1 }))
    expect(next).toEqual({ ...base, seq: 3 })
  })
})

describe('a check with nothing to write', () => {
  it('shows the gate and the write as not needed', () => {
    const model = foldAll(replay(success, 8), [event(9, 'run_succeeded', { outcome: 'nothing_to_write' })])
    expect(shape(stationsOf(model, PLAN, writeLabel))).toEqual([
      'started:done:idle',
      'planner:done:idle',
      'agent:0:done:success',
      'gate:skip:idle',
      'write:skip:idle',
      'done:done:idle',
    ])
  })
})
