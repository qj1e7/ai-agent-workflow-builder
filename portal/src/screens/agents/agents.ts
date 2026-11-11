import { connectorLabel } from '../../api/labels'
import type { CardView, ToolId, ToolView } from '../../api/types'

export interface PlatformAgent {
  readonly id: string
  readonly what: string
  readonly reach: string
  readonly steps: readonly string[]
  readonly rules: readonly string[]
}

/** The agents the platform ships with. They are not cards, so they come from this list and not from the API. */
export const PLATFORM_AGENTS: readonly PlatformAgent[] = [
  {
    id: 'planner',
    what: 'Answers questions about your watchlist and sets up software to watch.',
    reach: 'It only plans.',
    steps: [
      'Read the task and say what it understood',
      'Pick saved agents that fit, or draft a new agent card',
      'Send release checks to the Software watchlist',
    ],
    rules: ['Never chooses who approves', 'Can only give an agent tools from the tool list'],
  },
  {
    id: 'troubleshooter',
    what: 'When a run stops, it explains why in plain words, and says whether you can fix it or support should.',
    reach: 'It reads the run’s own record.',
    steps: ['Read the stopped run’s record', 'Explain what went wrong in plain words', 'Say whether you can fix it, or support should'],
    rules: ['Only explains. It never changes a run'],
  },
]

export const PLATFORM_NOTE = 'This agent is part of the platform, so only the team that runs the platform can change it.'
export const CHANGE_LATER_NOTE = 'Changing an agent in plain English is coming later.'
const TOOLS_UNAVAILABLE_WORDS = 'The tool list is not available right now.'

export function toolsUnavailableWords(cardsBelow: boolean): string {
  return cardsBelow ? `${TOOLS_UNAVAILABLE_WORDS} The agent cards below are still here.` : TOOLS_UNAVAILABLE_WORDS
}

export const PLATFORM_AGENT_MARK = 'Platform agent'

export function systemOf(tool: ToolId): string {
  const [system = tool] = tool.split('.')
  return connectorLabel(system)
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

export type HowShow = 'can' | 'agents' | 'tools'

/** Which of How it works' own tabs an address asks for. An agent's address opens on the Agents tab, where its tile is. */
export function howShowOf(show: string | null, agent: string | null): HowShow {
  if (show === 'agents' || show === 'tools') return show
  return agent === null ? 'can' : 'agents'
}

/** Where How it works, or one agent in it, lives in Settings. */
export function howItWorksPath({ show = null, agent = null }: { show?: string | null; agent?: string | null } = {}): string {
  const params = new URLSearchParams({ tab: 'how' })
  const tab = howShowOf(show, agent)
  if (tab !== 'can') params.set('show', tab)
  if (agent !== null) params.set('agent', agent)
  return `/settings?${params.toString()}`
}

/** True when an address names an agent that has a page to open: a platform agent, or a card the platform lists. */
export function agentShown(agentId: string | null, cards: readonly Pick<CardView, 'card_id'>[] | undefined): boolean {
  if (agentId === null) return false
  return PLATFORM_AGENTS.some((agent) => agent.id === agentId) || (cards?.some((card) => card.card_id === agentId) ?? false)
}
