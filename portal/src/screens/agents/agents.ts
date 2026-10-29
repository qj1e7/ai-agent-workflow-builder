import type { CardView, ToolId, ToolView } from '../../api/types'

export interface PlatformAgent {
  readonly id: string
  readonly what: string
  readonly steps: readonly string[]
  readonly rules: readonly string[]
}

/** The agents the platform ships with. They are not cards, so they come from this list and not from the API. */
export const PLATFORM_AGENTS: readonly PlatformAgent[] = [
  {
    id: 'planner',
    what: 'Reads each task, says what it understood, and picks the agents for each workflow. When none of them fits, it drafts a new agent card for you to check.',
    steps: [
      'Read the task and say what it understood',
      'Pick saved agents that fit, or draft a new agent card',
      'Send release and vulnerability checks to the Software watchlist',
    ],
    rules: ['Never chooses who approves', 'Can only give an agent tools from the tool list'],
  },
  {
    id: 'troubleshooter',
    what: 'When a run stops, it explains why in plain words, and says whether you can fix it or support should.',
    steps: ['Read the stopped run’s record', 'Explain what went wrong in plain words', 'Say whether you can fix it, or support should'],
    rules: ['Only explains. It never changes a run'],
  },
]

export const PLATFORM_AGENT_IDS: readonly string[] = PLATFORM_AGENTS.map((agent) => agent.id)

export const PLATFORM_NOTE = 'This agent is part of the platform, so only the team that runs the platform can change it.'
export const CHANGE_LATER_NOTE = 'Changing an agent in plain English is coming later.'
const TOOLS_UNAVAILABLE_WORDS = 'The tool list is not available right now.'

export function toolsUnavailableWords(cardsBelow: boolean): string {
  return cardsBelow ? `${TOOLS_UNAVAILABLE_WORDS} The agent cards below are still here.` : TOOLS_UNAVAILABLE_WORDS
}

export function isPlatformAgent(id: string): boolean {
  return PLATFORM_AGENT_IDS.includes(id)
}

export function platformAgentMark(id: string): string | null {
  return isPlatformAgent(id) ? 'Platform agent' : null
}

export function kindLabel(kind: ToolView['kind']): string {
  return kind === 'write' ? 'Changes data' : 'Reads only'
}

export function approvalWords(min: number | null): string {
  if (min === null || min <= 0) return 'Waits for a yes'
  return min === 1 ? 'Waits for a yes from 1 Approver' : `Waits for a yes from ${min} Approvers, one after the other`
}

export function toolCountWords(count: number): string {
  return count === 1 ? '1 tool' : `${count} tools`
}

export type Access = 'none' | 'reads' | 'writes'

export function accessLabel(access: Access): string {
  return { none: 'No access to other systems', reads: 'Reads only', writes: 'Changes data after a yes' }[access]
}

/** The tool list can be down while the cards load, so an approval on the card counts as a write too. */
export function cardAccess(card: Pick<CardView, 'tools' | 'approvals'>, kinds: ReadonlyMap<ToolId, ToolView['kind']>): Access {
  if (card.tools.length === 0) return 'none'
  if (card.approvals.length > 0 || card.tools.some((tool) => kinds.get(tool) === 'write')) return 'writes'
  return 'reads'
}

/** A starter card's id reads crd_version_checker, which is the id its face and colours are keyed on. */
export function faceId(card: Pick<CardView, 'card_id'>): string {
  return card.card_id.replace(/^crd_/, '')
}

export function versionWords(card: Pick<CardView, 'starter' | 'version'>): string {
  return card.starter ? `Version ${card.version}. Ships with the platform` : `Version ${card.version}`
}

export function toolKinds(tools: readonly ToolView[] | undefined): ReadonlyMap<ToolId, ToolView['kind']> {
  return new Map((tools ?? []).map((tool) => [tool.id, tool.kind]))
}
