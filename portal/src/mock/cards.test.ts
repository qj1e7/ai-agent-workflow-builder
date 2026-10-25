import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActivityEvent, CardChecked, CardView, PlanOut, UseCaseView } from '../api/types'
import { checkCard, cardPlan } from './cards'
import { fixtures } from './fixtures'
import { createDemoPlatform, type DemoPlatformHandle } from './index'

const START = Date.parse('2026-11-27T02:00:00Z')
const ORIGIN = 'http://portal.test/api/v1'
const KEY = 'sk-example-key-not-real-x7'

let demo: DemoPlatformHandle

beforeEach(() => {
  vi.useFakeTimers({ now: START })
  demo = createDemoPlatform(START)
})

afterEach(() => {
  vi.useRealTimers()
})

async function call(method: string, path: string, body?: unknown, user = 'alice', headers: Record<string, string> = {}): Promise<Response> {
  const sent = new Headers(headers)
  sent.set('X-Dev-User', user)
  if (body !== undefined) sent.set('Content-Type', 'application/json')
  const init: RequestInit = { method, headers: sent }
  if (body !== undefined) init.body = JSON.stringify(body)
  return demo.fetch(`${ORIGIN}${path}`, init)
}

async function connectModel(): Promise<void> {
  const saved = await call('PUT', '/settings/model', {
    style: 'anthropic',
    base_url: 'https://llm-gateway.aisg.sg',
    model: 'claude-haiku-5-5',
    api_key: KEY,
    use_saved_key: false,
  })
  expect(saved.status).toBe(200)
}

async function plan(task: string, user = 'alice'): Promise<PlanOut> {
  const response = await call('POST', '/builder/plan', { task }, user)
  expect(response.status).toBe(200)
  return (await response.json()) as PlanOut
}

const weekly = {
  name: 'Weekly finished work',
  purpose: 'Raises a ticket that lists what was finished.',
  good_for: [],
  inputs: [{ name: 'Jira project', kind: 'jira_project', what: '', example: 'MOCK' }],
  blocks: [
    { say: 'Find the tickets finished this week.', tool: 'jira.search' },
    { say: 'Propose a ticket that lists them.', tool: 'jira.create_ticket' },
  ],
  approvals: [],
}

describe('checking a card', () => {
  it('accepts a whole card and asks for the tool minimum of approvals', () => {
    const checked = checkCard(weekly)
    expect(checked.problems).toEqual([])
    expect(checked.approvals).toEqual([{ tool: 'jira.create_ticket', approvers: 1 }])
  })

  it('caps the approvals asked for at two and drops tools the steps do not use', () => {
    const checked = checkCard({ ...weekly, approvals: [{ tool: 'jira.create_ticket', approvers: 9 }, { tool: 'jira.search', approvers: 2 }] })
    expect(checked.approvals).toEqual([{ tool: 'jira.create_ticket', approvers: 2 }])
    expect(checkCard({ ...weekly, blocks: [weekly.blocks[0] as (typeof weekly.blocks)[number]] }).approvals).toEqual([])
  })

  it('says what is missing, next to the field', () => {
    const checked = checkCard({ ...weekly, name: '', inputs: [], blocks: [{ say: '', tool: 'slack.post' }] })
    expect(checked.problems.map((each) => each.field)).toEqual(['name', 'blocks.0.say', 'blocks.0.tool'])
    const noProject = checkCard({ ...weekly, inputs: [] })
    expect(noProject.problems.map((each) => each.field)).toEqual(['inputs'])
    expect(noProject.problems[0]?.message).toContain('Add a Jira project detail')
  })

  it('refuses an old themed name', () => {
    expect(checkCard({ ...weekly, name: 'Forge reporter' }).problems[0]).toMatchObject({ field: 'name' })
  })
})

describe('the card routes', () => {
  it('lists the tools and the library with the starter first', async () => {
    const { tools } = (await (await call('GET', '/tools')).json()) as { tools: { id: string }[] }
    expect(tools.map((tool) => tool.id)).toContain('jira.create_ticket')
    const { cards } = (await (await call('GET', '/agent-cards')).json()) as { cards: CardView[] }
    expect(cards.map((card) => [card.name, card.starter])).toEqual([['Release checker', true], ['Weekly summary', false]])
  })

  it('checks a card with the platform shape', async () => {
    const checked = (await (await call('POST', '/agent-cards/check', { ...weekly, inputs: [] })).json()) as CardChecked
    expect(checked.problems).toHaveLength(1)
    expect(checked.approvals).toHaveLength(1)
  })

  it('saves a card, then a next version, and never changes a starter', async () => {
    const created = await call('POST', '/agent-cards', weekly)
    expect(created.status).toBe(201)
    const card = (await created.json()) as CardView
    expect([card.version, card.owner, card.tools]).toEqual([1, 'alice', ['jira.search', 'jira.create_ticket']])
    const next = await call('PUT', `/agent-cards/${card.card_id}`, { ...weekly, name: 'Friday work' })
    expect(((await next.json()) as CardView).version).toBe(2)
    const starter = await call('PUT', '/agent-cards/crd_release_checker', weekly)
    expect([starter.status, ((await starter.json()) as { detail: string }).detail]).toEqual([409, 'Starter agents cannot be changed. Copy it instead.'])
  })

  it('refuses a card with problems, and a save by an Approver', async () => {
    const refused = await call('POST', '/agent-cards', { ...weekly, inputs: [] })
    expect(refused.status).toBe(422)
    expect(((await refused.json()) as { problems: unknown[] }).problems).toHaveLength(1)
    expect((await call('POST', '/agent-cards', weekly, 'bob')).status).toBe(403)
  })
})

describe('planning', () => {
  it('asks for an AI model first', async () => {
    const refused = await call('POST', '/builder/plan', { task: 'Check releases' })
    expect([refused.status, ((await refused.json()) as { detail: string }).detail]).toEqual([409, 'Connect an AI model in Settings first.'])
  })

  it('picks the starter for a release task and marks the Jira project missing', async () => {
    await connectModel()
    const answer = await plan('Every Monday, check acme/widgets for new releases and open a ticket.')
    expect(answer).toMatchObject({ decision: 'use_one', agents: [{ values: { 'GitHub repository': 'acme/widgets' }, missing: ['Jira project'] }] })
  })

  it('drafts a new agent for a summary, with the problems the Operator must fix', async () => {
    await connectModel()
    const answer = await plan('Every Friday summarise what we finished and raise a ticket.')
    expect(answer.decision).toBe('new_agent')
    if (answer.decision !== 'new_agent') return
    expect(answer.problems.map((each) => each.field)).toEqual(['inputs'])
    expect(answer.missing_tools.length).toBeGreaterThan(0)
  })

  it('says it cannot book a meeting room', async () => {
    await connectModel()
    expect((await plan('Book a meeting room for Friday.')).decision).toBe('cannot_do')
  })
})

describe('agent use cases and their runs', () => {
  const choice = { card_id: 'crd_release_checker', values: { 'GitHub repository': 'acme/widgets', 'Jira project': 'ABC' } }

  async function made(): Promise<UseCaseView> {
    const created = await call('POST', '/agent-use-cases', { name: 'Widgets', instruction: 'Check widgets.', agents: [choice] })
    expect(created.status).toBe(201)
    const { use_case_id: id } = (await created.json()) as { use_case_id: string }
    return (await (await call('GET', `/use-cases/${id}`)).json()) as UseCaseView
  }

  it('stores the plan the line is drawn from: the agent, the gate and the write', async () => {
    const useCase = await made()
    expect(useCase).toMatchObject({ template: 'agent_cards', params: {}, agents: [{ card_id: 'crd_release_checker', card_version: 1 }] })
    expect(useCase.plan.map((block) => [block.key, block.kind])).toEqual([
      ['crd_release_checker', 'agent'],
      ['approval_gate', 'approval'],
      ['jira_create_ticket', 'write_action'],
    ])
  })

  it('draws only the agent for a card that never writes', () => {
    const readOnly = fixtures.cards.filter((card) => card.tools.every((id) => id.startsWith('jira.search')))
    expect(cardPlan(readOnly).map((block) => block.kind)).toEqual(['agent'])
  })

  it('names the field the platform refuses', async () => {
    const bad = await call('POST', '/agent-use-cases', {
      name: 'Widgets',
      instruction: 'x',
      agents: [{ ...choice, values: { 'GitHub repository': 'nope', 'Jira project': 'ABC' } }],
    })
    expect(bad.status).toBe(422)
    expect(((await bad.json()) as { detail: { loc: unknown[] }[] }).detail[0]?.loc).toEqual(['body', 'agents', 0, 'values', 'GitHub repository'])
    const gone = await call('POST', '/agent-use-cases', { name: 'W', instruction: 'x', agents: [{ card_id: 'crd_none', values: {} }] })
    expect(((await gone.json()) as { detail: { loc: unknown[] }[] }).detail[0]?.loc).toEqual(['body', 'agents', 0, 'card_id'])
  })

  it('answers 409 when no model is connected, then plays the recorded card run with its own repository and project', async () => {
    const useCase = await made()
    const start = () => call('POST', `/use-cases/${useCase.use_case_id}/runs`, undefined, 'alice', { 'Idempotency-Key': 'k1' })
    const refused = await start()
    expect([refused.status, ((await refused.json()) as { detail: string }).detail]).toEqual([409, 'Connect an AI model in Settings to run agents.'])
    await connectModel()
    const started = await start()
    expect(started.status).toBe(201)
    const { run_id: runId } = (await started.json()) as { run_id: string }
    await vi.advanceTimersByTimeAsync(20_000)
    const { events } = (await (await call('GET', `/runs/${runId}/events`)).json()) as { events: ActivityEvent[] }
    const steps = events.flatMap((event) => (event.kind === 'agent_step_started' ? [event.data.step] : []))
    expect(steps).toEqual(['github_read_releases', 'jira_search', 'jira_create_ticket'])
    const text = JSON.stringify(events)
    expect(text).toContain('acme/widgets')
    expect(text).toContain('Jira project ABC')
    expect(text).not.toContain('langchain-ai')
  })
})
