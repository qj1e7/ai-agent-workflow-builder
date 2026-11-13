import useCase from '@contracts/fixtures/builder/use-case.json'
import cardUseCase from '@contracts/fixtures/builder/use-case.versioned.json'
import card from '@contracts/fixtures/runs/card.json'
import expired from '@contracts/fixtures/runs/expired.json'
import failure from '@contracts/fixtures/runs/failure.json'
import lost from '@contracts/fixtures/runs/lost.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { describe, expect, it } from 'vitest'
import type { BlockKind } from '../../api/types'
import { runId } from '../../stream/brand'
import { parseEvent, type RunEvent } from '../../stream/parse'
import { emptyModel, fold, foldAll, isFinished, stationsOf, type PlanBlock, type RunModel, type Station } from './runModel'

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

const planOf = (blocks: readonly { key: string; name: string; kind: string }[]): PlanBlock[] => blocks.map((block) => ({ key: block.key, name: block.name, kind: block.kind as BlockKind }))
const PLAN = planOf(useCase.plan)
const STARTED = 'Started by Alice'
const line = (model: RunModel, plan: readonly PlanBlock[] | null = PLAN) => stationsOf(model, plan, STARTED)

const shape = (stations: readonly Station[]) => stations.map((s) => `${s.key}:${s.state}:${s.face}`)
const at = (iso: string) => Date.parse(iso)
/** When the step's timer counts from: only the step at work has one. */
const since = (station: Station | undefined) => (station?.under?.kind === 'timer' ? station.under.since : null)

function event(seq: number, kind: string, data: Record<string, unknown>, actor = { kind: 'platform', id: 'platform', display: 'Platform' }, ts = '2026-11-04T02:20:00Z'): RunEvent {
  const result = parseEvent({ run_id: 'run_01JB9', seq, ts, actor, summary: '', kind, data }, runId('run_01JB9'))
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
    expect(model.written.map((w) => w.url)).toEqual(['/jira/MOCK-142'])
    expect(model.approvedBy).toEqual(['bob'])
    expect(model.startedBy).toBe('alice')
    expect(model.people).toMatchObject({ alice: 'Alice', bob: 'Bob' })
    expect(model.approvalId).toBe('apr_01JB8')
  })

  it('draws only the workflow’s blocks, every one done, with the agent that did the work happy', () => {
    expect(shape(line(model))).toEqual(['trigger:done:idle', 'agent:0:done:success', 'gate:done:idle', 'write:done:idle'])
  })

  it('puts the ticket it wrote under the write, and nothing under any other step', () => {
    expect(line(model).map((s) => s.under)).toEqual([null, null, null, { kind: 'tickets', written: [{ connector: 'jira', operation: 'create_ticket', ref: 'MOCK-142', url: '/jira/MOCK-142' }] }])
  })

  it('names the steps from the plan, the gate as asking for a yes, and puts the agent above its step', () => {
    const stations = line(model)
    expect(stations.map((s) => s.label)).toEqual(['Started by Alice', 'Read every source', 'Ask for a yes', 'Create Jira tickets'])
    expect(stations.map((s) => s.icon)).toEqual(['person', 'read', 'gate', 'write'])
    expect(stations.map((s) => s.agent)).toEqual([null, { id: 'version_checker', display: 'Version checker' }, null, null])
  })

  it('says the version checker’s step in the sketch’s words, and the write in the plan’s', () => {
    const cardRun = replay(card)
    expect(line(cardRun, planOf(cardUseCase.plan)).map((s) => s.label)).toEqual(['Started by Alice', 'Check release', 'Ask for a yes', 'Create Jira tickets'])
  })

  it('draws the same line without a plan, naming steps after their agents', () => {
    expect(line(model, null).map((s) => s.label)).toEqual(['Started by Alice', 'Version checker', 'Ask for a yes', 'Write in Jira'])
  })

  it('starts with the schedule’s clock when the schedule started the run', () => {
    const scheduled = foldAll(emptyModel, [event(1, 'run_created', { use_case_id: 'uc_1', use_case_version: 1, started_by: 'alice', trigger: 'schedule' })])
    const first = stationsOf(scheduled, PLAN, 'Daily 8:00')[0]
    expect(first).toMatchObject({ label: 'Daily 8:00', icon: 'schedule', state: 'done' })
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
  it('while the Version checker reads, has the checker’s step at work and the rest not reached', () => {
    const model = replay(success, 6)
    expect(model.phase.state).toBe('working')
    expect(shape(line(model))).toEqual(['trigger:done:idle', 'agent:0:now:working', 'gate:todo:idle', 'write:todo:idle'])
  })

  it('while the Planner picks the agents, has the first step at work with the Planner above it', () => {
    const model = replay(success, 3)
    const stations = line(model)
    expect(stations).toHaveLength(4)
    expect(shape(stations)).toEqual(['trigger:done:idle', 'agent:0:now:thinking', 'gate:todo:idle', 'write:todo:idle'])
    expect(stations[1]?.agent).toEqual({ id: 'planner', display: 'Planner' })
  })

  it('without a plan, keeps one agent step for the Planner’s pick, so the gate is never the step at work', () => {
    const model = replay(success, 1)
    expect(shape(line(model, null))).toEqual(['trigger:done:idle', 'agent:0:now:thinking', 'gate:todo:idle', 'write:todo:idle'])
  })

  it('times the first step from the start of the run, through the Planner’s pick, and no other step', () => {
    const started = at(success[0]?.ts ?? '')
    for (const upTo of [1, 3, 4, 6]) expect(line(replay(success, upTo)).map(since)).toEqual([null, started, null, null])
  })

  it('at the gate, waits for a yes with the agent’s step done', () => {
    const model = replay(success, 15)
    expect(model.phase.state).toBe('awaiting_approval')
    expect(shape(line(model))).toEqual(['trigger:done:idle', 'agent:0:done:success', 'gate:wait:idle', 'write:todo:idle'])
    expect(line(model).map(since)).toEqual([null, null, null, null])
  })

  it('after the yes, writes while the gate shows done, timing the write from the yes', () => {
    const model = replay(success, 16)
    expect(model.phase.state).toBe('acting')
    const stations = line(model)
    expect(shape(stations).slice(2)).toEqual(['gate:done:idle', 'write:now:idle'])
    expect(since(stations[3])).toBe(at(success[15]?.ts ?? ''))
  })
})

describe('a run that was declined', () => {
  const model = replay(rejected)

  it('ends rejected, naming who declined and at which step', () => {
    expect(model.phase).toEqual({ state: 'rejected', by: 'bob', step: 0 })
    expect(model.written).toEqual([])
  })

  it('shows the gate as declined and the write as skipped, with no step after them', () => {
    expect(shape(line(model))).toEqual(['trigger:done:idle', 'agent:0:done:success', 'gate:no:idle', 'write:skip:idle'])
    expect(line(model)[3]?.under).toEqual({ kind: 'note', text: 'Nothing written' })
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
    expect(shape(line(model))).toEqual(['trigger:done:idle', 'agent:0:err:error', 'gate:todo:idle', 'write:todo:idle'])
  })

  it('lets the agent say what went wrong, and ends the chat with the stop', () => {
    const bad = model.chat.filter((item) => item.kind === 'said' && item.bad)
    expect(bad).toHaveLength(1)
    expect(bad[0]).toMatchObject({ speaker: { id: 'version_checker' } })
    expect(model.chat.at(-1)).toMatchObject({ kind: 'stopped', stage: 'working' })
  })

  it('marks the first step, under the Planner, when a run fails before any agent starts', () => {
    const early = foldAll(emptyModel, [
      ...parsed(failure.slice(0, 2)),
      event(3, 'run_failed', { stage: 'pending', reason: 'DispatchFailed', retryable: true, message: 'n8n is down' }),
    ])
    expect(shape(line(early))).toEqual(['trigger:done:idle', 'agent:0:err:error', 'gate:todo:idle', 'write:todo:idle'])
    expect(line(early)[1]?.agent).toEqual({ id: 'planner', display: 'Planner' })
    expect(shape(line(early, null)), 'and without a plan, never the gate').toEqual(['trigger:done:idle', 'agent:0:err:error', 'gate:todo:idle', 'write:todo:idle'])
  })
})

describe('a report to support', () => {
  const alice = { kind: 'user', id: 'alice', display: 'Alice' }
  const failed = replay(failure)
  const reported = fold(failed, event(15, 'support_reported', { request_id: 'trq_1', reported_by: 'alice' }, alice))

  it('is kept once for each request, with who made it, and says so in the activity once', () => {
    expect(reported.reports).toEqual([{ requestId: 'trq_1', by: 'alice' }])
    expect(reported.chat.at(-1)).toMatchObject({ kind: 'reported', by: 'alice', requestId: 'trq_1' })
    const again = fold(reported, event(16, 'support_reported', { request_id: 'trq_1', reported_by: 'alice' }, alice))
    expect(again.reports).toHaveLength(1)
    expect(again.chat.filter((item) => item.kind === 'reported')).toHaveLength(1)
  })

  it('leaves the run as it was, still stopped', () => {
    expect(reported.phase).toEqual(failed.phase)
    expect(reported.seq).toBe(15)
  })

  it('is forgotten when the run is retried, so a new stop can be reported again', () => {
    const retried = fold(reported, event(16, 'run_retried', { leg: 'work', attempt: 2 }, alice))
    expect(retried.reports).toEqual([])
  })
})

describe('what the agents found', () => {
  it('is read from the step that closed their work, and stays after the run is decided', () => {
    expect(replay(success).found).toBe('LangGraph has a new release: 1.2.16.')
    expect(replay(success, 20).found).toBe('LangGraph has a new release: 1.2.16.')
    expect(replay(failure).found).toBe('')
  })

  it('starts again when the work is retried', () => {
    const alice = { kind: 'user', id: 'alice', display: 'Alice' }
    const retried = fold(replay(success.slice(0, 20)), event(21, 'run_retried', { leg: 'work', attempt: 2 }, alice))
    expect(retried.found).toBe('')
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
    expect(shape(line(retried))).toEqual(['trigger:done:idle', 'agent:0:now:thinking', 'gate:todo:idle', 'write:todo:idle'])
  })

  it('times the step at work again from the retry', () => {
    expect(since(line(retried)[1])).toBe(at('2026-11-04T02:20:00Z'))
  })

  it('draws the second attempt as it goes', () => {
    const again = foldAll(retried, [
      event(16, 'agent_joined', { agent: { id: 'version_checker', display: 'Version checker' }, reason: 'again' }, { kind: 'agent', id: 'planner', display: 'Planner' }, '2026-11-04T02:20:04Z'),
      event(17, 'agent_step_started', { step: 'read_source' }, { kind: 'agent', id: 'version_checker', display: 'Version checker' }, '2026-11-04T02:20:05Z'),
    ])
    expect(again.phase.state).toBe('working')
    expect(shape(line(again)).slice(0, 2)).toEqual(['trigger:done:idle', 'agent:0:now:working'])
    expect(since(line(again)[1]), 'the step began at the retry, not when its agent came in').toBe(at('2026-11-04T02:20:00Z'))
  })

  it('after a failed write, carries on at the write without asking again', () => {
    const writeFailed = { ...failed, phase: { state: 'failed', stage: 'acting', reason: 'WriteFailed', retryable: true, message: '' } } as const
    const again = fold({ ...writeFailed, failedAt: { at: 'write' } }, event(15, 'run_retried', { leg: 'act', attempt: 2 }, alice))
    expect(again.phase).toEqual({ state: 'acting' })
    expect(again.spot).toEqual({ at: 'write' })
    expect(shape(line(again)).slice(2)).toEqual(['gate:done:idle', 'write:now:idle'])
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

  it('move only the cursor for an outcome card that could not go to the channel that had the request', () => {
    const decided = replay(success)
    const note = event(decided.seq + 1, 'approval_outcome_not_posted', { approval_id: 'apr_01JB8', channel: 'CODESparks Ops' })
    expect(note.kind).toBe('approval_outcome_not_posted')
    expect(fold(decided, note)).toEqual({ ...decided, seq: decided.seq + 1 })
  })
})

describe('a check with nothing to write', () => {
  it('shows the gate and the write as skipped', () => {
    const model = foldAll(replay(success, 8), [event(9, 'run_succeeded', { outcome: 'nothing_to_write' })])
    expect(shape(line(model))).toEqual(['trigger:done:idle', 'agent:0:done:success', 'gate:skip:idle', 'write:skip:idle'])
  })
})

describe('a run n8n skipped because an earlier run still waits for a yes', () => {
  const started = fold(emptyModel, event(1, 'run_created', { started_by: 'alice', use_case_id: 'uc_01', trigger: 'schedule' }))
  const linked = fold(started, event(2, 'execution_linked', { execution_id: '41', mode: 'trigger' }, { kind: 'workflow', id: 'n8n', display: 'Workflow engine' }))
  const model = fold(linked, event(3, 'run_skipped', { waiting_run_id: 'run_00' }))

  it('ends skipped: its trigger fired, and every step after it was skipped', () => {
    expect(linked.phase).toEqual({ state: 'pending' })
    expect(model.phase).toEqual({ state: 'skipped' })
    const [trigger, ...steps] = line(model)
    expect(trigger?.state).toBe('done')
    expect(steps.length).toBeGreaterThan(0)
    expect(steps.every((station) => station.state === 'skip')).toBe(true)
  })
})

describe('a run n8n waits on that ends with no answer, or that n8n lost after the yes', () => {
  const ended = (model: RunModel, key: string) => line(model).find((station) => station.key === key)?.state

  it('ends expired, with the gate and the write skipped', () => {
    const model = replay(expired)
    expect(model.phase).toEqual({ state: 'expired' })
    expect(isFinished(model.phase)).toBe(true)
    expect([ended(model, 'gate'), ended(model, 'write')]).toEqual(['skip', 'skip'])
  })

  it('ends lost after the yes, with nothing written', () => {
    const model = replay(lost)
    expect(model.phase).toEqual({ state: 'lost' })
    expect(isFinished(model.phase)).toBe(true)
    expect([ended(model, 'gate'), ended(model, 'write')]).toEqual(['done', 'skip'])
  })
})
