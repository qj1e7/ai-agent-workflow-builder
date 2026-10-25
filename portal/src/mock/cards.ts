import type {
  BlockView,
  CardApprovalView,
  CardChecked,
  CardDefinition,
  CardProblem,
  CardView,
  DevUser,
  InputKind,
  PlanOut,
  ToolView,
  UseCaseView,
} from '../api/types'
import { fixtures } from './fixtures'
import { invalid, isRecord, json, problem } from './http'

// The demo plays the platform's agent cards in the browser: the library, the check, the Room lead's scripted plan.

const OPERATORS_ONLY = 'Only an Operator can do this. Ask an Operator on the team.'
const STARTER_WORDS = 'Starter agents cannot be changed. Copy it instead.'
export const NO_MODEL_PLAN = 'Connect an AI model in Settings first.'
export const NO_MODEL_RUN = 'Connect an AI model in Settings to run agents.'
const THEMED = /\b(Flint|Forge|Striker|Spark Map|Scout|Analyst|Messenger|Clerk|Fixer|Kindling|Firebreak|Ember)\b/i
const KINDS: readonly InputKind[] = ['github_repo', 'jira_project', 'text']
const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/
const PROJECT = /^[A-Z][A-Z0-9]{0,9}$/
const NAME_LIMIT = 80
const PURPOSE_LIMIT = 300
const MOST_APPROVERS = 2
const MOST_AGENTS = 3

const tools = fixtures.tools
const starters = fixtures.cards.filter((card) => card.starter)

function toolOf(id: string | null | undefined): ToolView | undefined {
  return tools.find((tool) => tool.id === id)
}

function listed(items: readonly string[]): string {
  return items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items.at(-1) ?? ''}`
}

/** The platform's check of a card, in the demo: the same rules, in the same words. */
export function checkCard(card: CardDefinition): CardChecked {
  const name = card.name.trim()
  const purpose = card.purpose.trim()
  const inputs = (card.inputs ?? []).map((input) => ({
    name: input.name.trim(),
    kind: input.kind,
    what: input.what.trim(),
    example: input.example.trim(),
  }))
  const blocks = (card.blocks ?? []).map((block) => ({ say: block.say.trim(), tool: block.tool || null }))
  const problems: CardProblem[] = []
  const add = (field: string | null, message: string) => problems.push({ field, message })

  const themed = (text: string) => THEMED.exec(text)?.[1]
  if (name === '') add('name', 'Give the agent a name.')
  else if (name.length > NAME_LIMIT) add('name', `Keep the name to ${NAME_LIMIT} characters.`)
  else if (themed(name)) add('name', `${themed(name)} is an old name that confused the sponsor. Use plain words.`)
  if (purpose === '') add('purpose', 'Say what the agent does.')
  else if (purpose.length > PURPOSE_LIMIT) add('purpose', `Keep this to ${PURPOSE_LIMIT} characters.`)
  else if (themed(purpose)) add('purpose', `${themed(purpose)} is an old name that confused the sponsor. Use plain words.`)

  if (blocks.length === 0) add('blocks', 'Add at least one step.')
  blocks.forEach((block, at) => {
    if (block.say === '') add(`blocks.${at}.say`, 'Say what this step does.')
    if (block.tool !== null && !toolOf(block.tool)) add(`blocks.${at}.tool`, 'This tool is not on the list.')
  })

  const seen = new Set<string>()
  inputs.forEach((input, at) => {
    if (input.name === '') add(`inputs.${at}.name`, 'Name this detail.')
    else if (seen.has(input.name)) add(`inputs.${at}.name`, `Two details are called ${input.name}.`)
    seen.add(input.name)
    if (!KINDS.includes(input.kind as InputKind)) add(`inputs.${at}.kind`, 'Pick a kind.')
  })

  const used = blocks.flatMap((block) => (toolOf(block.tool) ? [toolOf(block.tool) as ToolView] : []))
  const needing = used.filter((tool) => tool.kind === 'write' || tool.id.startsWith('jira.'))
  const projects = inputs.filter((input) => input.kind === 'jira_project').length
  if (needing.length > 0 && projects !== 1) {
    const names = [...new Set(needing.map((tool) => tool.name))]
    add(
      'inputs',
      projects === 0
        ? `${listed(names)} needs one input of kind jira_project, so the agent knows which project it may read. Add one.`
        : `${listed(names)} needs exactly one input of kind jira_project. Remove the others.`,
    )
  }

  const asked = card.approvals ?? []
  const approvals: CardApprovalView[] = [...new Set(used.filter((tool) => tool.kind === 'write').map((tool) => tool.id))].map((tool) => ({
    tool,
    approvers: Math.min(
      MOST_APPROVERS,
      Math.max(toolOf(tool)?.min_approvers ?? 1, asked.find((each) => each.tool === tool)?.approvers ?? 1),
    ),
  }))

  return {
    card: { name, purpose, good_for: [...(card.good_for ?? [])], inputs, blocks, approvals },
    approvals,
    problems,
  }
}

/** The blocks a run of these cards draws: each agent, the approval gate, and one write for each kind of write. */
export function cardPlan(cards: readonly CardView[]): BlockView[] {
  const writes = [...new Set(cards.flatMap((card) => card.tools).filter((id) => toolOf(id)?.kind === 'write'))]
  const blocks: BlockView[] = cards.map((card) => ({
    key: card.card_id,
    name: card.name,
    description: card.purpose,
    kind: 'agent',
  }))
  if (writes.length === 0) return blocks
  blocks.push({
    key: 'approval_gate',
    name: 'Approval gate',
    description: 'An Approver reviews what the agents propose in Teams before anything is written.',
    kind: 'approval',
  })
  for (const id of writes) {
    blocks.push({
      key: id.replace('.', '_'),
      name: 'Create Jira tickets',
      description: `${toolOf(id)?.name ?? id}, written only after approval.`,
      kind: 'write_action',
    })
  }
  return blocks
}

function valueFits(kind: InputKind, value: string): boolean {
  if (kind === 'github_repo') return REPO.test(value)
  if (kind === 'jira_project') return PROJECT.test(value)
  return value.length >= 1 && value.length <= 200 && !/[\r\n]/.test(value)
}

function parseChoice(value: unknown): { card_id: string; values: Record<string, string> } | undefined {
  if (!isRecord(value) || typeof value['card_id'] !== 'string' || !isRecord(value['values'])) return undefined
  const entries = Object.entries(value['values'])
  if (!entries.every(([, each]) => typeof each === 'string')) return undefined
  return { card_id: value['card_id'], values: Object.fromEntries(entries) as Record<string, string> }
}

function parseDefinition(body: unknown): CardDefinition | undefined {
  if (!isRecord(body) || typeof body['name'] !== 'string' || typeof body['purpose'] !== 'string') return undefined
  const text = (each: unknown) => (typeof each === 'string' ? each : '')
  const inputs = Array.isArray(body['inputs']) ? body['inputs'] : []
  const blocks = Array.isArray(body['blocks']) ? body['blocks'] : []
  const approvals = Array.isArray(body['approvals']) ? body['approvals'] : []
  return {
    name: body['name'],
    purpose: body['purpose'],
    good_for: Array.isArray(body['good_for']) ? body['good_for'].filter((each) => typeof each === 'string') : [],
    inputs: inputs.filter(isRecord).map((input) => ({
      name: text(input['name']),
      kind: text(input['kind']),
      what: text(input['what']),
      example: text(input['example']),
    })),
    blocks: blocks.filter(isRecord).map((block) => ({ say: text(block['say']), tool: typeof block['tool'] === 'string' ? block['tool'] : null })),
    approvals: approvals.filter(isRecord).map((each) => ({ tool: text(each['tool']), approvers: Number(each['approvers']) || 1 })),
  }
}

const REPO_IN_TASK = /\b[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+\b/

export class DemoCards {
  private saved: CardView[]
  private counter = 0

  constructor(start: number) {
    this.saved = fixtures.cards
      .filter((card) => !card.starter)
      .map((card) => ({ ...card, created_at: new Date(start).toISOString() }))
  }

  tools(): ToolView[] {
    return tools
  }

  list(): CardView[] {
    return [...starters, ...[...this.saved].sort((a, b) => a.name.localeCompare(b.name))]
  }

  get(cardId: string): CardView | undefined {
    return this.list().find((card) => card.card_id === cardId)
  }

  check(body: unknown): Response {
    const card = parseDefinition(body)
    return card ? json(200, checkCard(card)) : invalid('name and purpose are required')
  }

  create(user: DevUser, body: unknown, wall: number): Response {
    if (!user.roles.includes('operator')) return problem(403, OPERATORS_ONLY)
    const parsed = parseDefinition(body)
    if (!parsed) return invalid('name and purpose are required')
    const checked = checkCard(parsed)
    if (checked.problems.length > 0) return json(422, { problems: checked.problems })
    this.counter += 1
    const view = this.view(`crd_demo${this.counter}`, 1, user, wall, checked)
    this.saved.push(view)
    return json(201, view)
  }

  update(user: DevUser, cardId: string, body: unknown, wall: number): Response {
    if (!user.roles.includes('operator')) return problem(403, OPERATORS_ONLY)
    const existing = this.get(cardId)
    if (!existing) return problem(404, 'There is no such agent.')
    if (existing.starter) return problem(409, STARTER_WORDS)
    const parsed = parseDefinition(body)
    if (!parsed) return invalid('name and purpose are required')
    const checked = checkCard(parsed)
    if (checked.problems.length > 0) return json(422, { problems: checked.problems })
    const next = { ...this.view(cardId, existing.version + 1, user, wall, checked), owner: existing.owner }
    this.saved = this.saved.map((card) => (card.card_id === cardId ? next : card))
    return json(200, next)
  }

  /** The Room lead's choice, scripted by a few words in the task. */
  plan(task: string): PlanOut {
    if (/meeting|room booking|book a|calendar/i.test(task)) return fixtures.planCannot
    if (/friday|summar/i.test(task)) {
      const draft: CardDefinition = {
        name: 'Weekly finished work',
        purpose: 'Raises a ticket that lists what was finished in a Jira project.',
        good_for: ['Raise a ticket listing what we finished this week'],
        inputs: [],
        blocks: [
          { say: 'Find the tickets finished this week.', tool: 'jira.search' },
          { say: 'Propose a ticket that lists them.', tool: 'jira.create_ticket' },
        ],
        approvals: [{ tool: 'jira.create_ticket', approvers: 1 }],
      }
      const checked = checkCard(draft)
      return {
        decision: 'new_agent',
        draft: checked.card,
        approvals: checked.approvals,
        problems: checked.problems,
        reason: fixtures.planNewAgent.reason,
        missing_tools: fixtures.planNewAgent.missing_tools,
        questions: fixtures.planNewAgent.questions,
      }
    }
    if (/release|version|github/i.test(task)) {
      const [agent] = fixtures.planUseOne.agents
      const card = starters[0]
      if (!agent || !card) return fixtures.planCannot
      const repo = REPO_IN_TASK.exec(task)?.[0]
      const values: Record<string, string> = repo ? { 'GitHub repository': repo } : {}
      const missing = card.inputs.map((input) => input.name).filter((each) => values[each] === undefined)
      return {
        decision: 'use_one',
        agents: [{ card, part: agent.part, values, missing }],
        reason: fixtures.planUseOne.reason,
        questions: missing.map((each) =>
          each === 'Jira project' ? 'Which Jira project should get the ticket?' : 'Which GitHub repository should it watch?',
        ),
      }
    }
    return {
      decision: 'cannot_do',
      reason: 'The platform has no tool for that yet.',
      missing_tools: [{ need: 'A tool for this task', why: 'The first agents read GitHub releases and read or propose Jira tickets.' }],
    }
  }

  /** A card use case from the agents chosen, or the 422 the platform would answer. */
  agentUseCase(
    body: unknown,
    owner: DevUser,
    id: string,
    wall: number,
  ): { kind: 'created'; useCase: UseCaseView } | { kind: 'refused'; response: Response } {
    const refused = (loc: (string | number)[], msg: string) => ({
      kind: 'refused' as const,
      response: json(422, { detail: [{ loc: ['body', ...loc], msg, type: 'value_error' }] }),
    })
    if (!isRecord(body)) return { kind: 'refused', response: invalid('a body is required') }
    const { name, instruction } = body
    if (typeof name !== 'string' || name.trim() === '' || name.length > NAME_LIMIT) return refused(['name'], 'name must be 1 to 80 characters')
    if (typeof instruction !== 'string' || instruction.trim() === '' || instruction.length > 2000) {
      return refused(['instruction'], 'instruction must be 1 to 2000 characters')
    }
    const choices = Array.isArray(body['agents']) ? body['agents'].map(parseChoice) : []
    if (choices.length < 1 || choices.length > MOST_AGENTS || choices.some((choice) => choice === undefined)) {
      return refused(['agents'], 'choose 1 to 3 agents')
    }
    const agents: UseCaseView['agents'] = []
    const cards: CardView[] = []
    for (const [at, choice] of choices.entries()) {
      const card = choice ? this.get(choice.card_id) : undefined
      if (!choice || !card) return refused(['agents', at, 'card_id'], 'unknown agent')
      for (const input of card.inputs) {
        if (!valueFits(input.kind, choice.values[input.name] ?? '')) return refused(['agents', at, 'values', input.name], 'not a valid value')
      }
      cards.push(card)
      agents.push({ card_id: card.card_id, card_version: card.version, name: card.name, values: choice.values })
    }
    return {
      kind: 'created',
      useCase: {
        use_case_id: id,
        version: 1,
        template: 'agent_cards',
        name: name.trim(),
        instruction: instruction.trim(),
        params: {},
        owner: owner.id,
        created_at: new Date(wall).toISOString(),
        plan: cardPlan(cards),
        agents,
      },
    }
  }

  private view(cardId: string, version: number, user: DevUser, wall: number, checked: CardChecked): CardView {
    const { card } = checked
    return {
      card_id: cardId,
      version,
      starter: false,
      owner: user.id,
      created_at: new Date(wall).toISOString(),
      name: card.name,
      purpose: card.purpose,
      good_for: card.good_for ?? [],
      inputs: (card.inputs ?? []).map((input) => ({ ...input, kind: input.kind as InputKind })),
      blocks: (card.blocks ?? []).map((block) => ({ say: block.say, tool: (block.tool ?? null) as CardView['blocks'][number]['tool'] })),
      approvals: checked.approvals,
      tools: [...new Set((card.blocks ?? []).flatMap((block) => (toolOf(block.tool) ? [toolOf(block.tool)?.id as ToolView['id']] : [])))],
    }
  }
}

