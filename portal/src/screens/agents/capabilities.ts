import type { CapabilityState, CapabilityView, CardView, ToolView } from '../../api/types'
import { runWhen } from '../workflows/times'

export type Group = 'ready' | 'needs_setup' | 'down' | 'not_yet'

export const GROUPS: readonly { readonly id: Group; readonly title: string }[] = [
  { id: 'ready', title: 'I can' },
  { id: 'needs_setup', title: 'Needs setup' },
  { id: 'down', title: 'Not working right now' },
  { id: 'not_yet', title: 'Not yet' },
]

export const NOT_YET_QUESTION = 'What can’t I do yet?'

export function groupOf(state: CapabilityState): Group {
  return state === 'planned' || state === 'unsupported' ? 'not_yet' : state
}

export const CAPABILITIES_UNAVAILABLE_WORDS = 'What the platform can do is not available right now.'
export const PLATFORM_DOES_WORDS = 'The platform does this for every workflow.'
export const CAPABILITIES_FOOT = 'Anything that changes data waits for a yes in Teams. Need something that isn’t here? Tell whoever looks after the platform. The team decides on new tools.'

/** What a ticket carries to the agents (agent-runtime jira.py). Stated once, for the line that reads tickets. */
export const JIRA_READ_FIELDS = ['key', 'project', 'title', 'status', 'created date', 'done date', 'last updated date', 'type', 'assignee', 'body'] as const

const when = (iso: string, now: Date) => runWhen(iso, now).replace(/^Today/, 'today')
const dot = (words: string) => (/[.!?]$/.test(words) ? words : `${words}.`)

export function agentNames(capability: CapabilityView, cards: readonly CardView[] | undefined): readonly string[] {
  return capability.agents.map((id) => cards?.find((card) => card.card_id === id)?.name ?? id)
}

/** The sentence under a capability: why it is not ready, what to do, and which agents use it. */
export function capabilityNote(capability: CapabilityView, cards: readonly CardView[] | undefined, now: Date): string {
  const parts: string[] = []
  switch (capability.state) {
    case 'down':
      parts.push(capability.last_ok_at ? `Last seen working ${when(capability.last_ok_at, now)}. Whatever uses it waits until it’s back.` : 'Whatever uses it waits until it’s back.')
      if (capability.fix) parts.push(dot(capability.fix))
      break
    case 'needs_setup':
      if (capability.why) parts.push(dot(capability.why))
      if (capability.fix) parts.push(dot(capability.fix))
      break
    case 'planned':
    case 'unsupported':
      if (capability.why) parts.push(dot(capability.why))
      break
    case 'ready':
      break
  }
  if (capability.platform) parts.push(PLATFORM_DOES_WORDS)
  else {
    const names = agentNames(capability, cards)
    if (names.length > 0 && capability.state !== 'planned' && capability.state !== 'unsupported') parts.push(`Used by ${names.join(', ')}.`)
  }
  return parts.join(' ')
}

export function fieldsNote(capability: CapabilityView): string | null {
  return capability.id === 'jira.read' ? `A ticket reaches the agents with these fields only: ${JIRA_READ_FIELDS.join(', ')}.` : null
}

export function settingsPathFor(capability: CapabilityView): string {
  return capability.connection === null && capability.needs_model ? '/settings?tab=model' : '/settings?tab=connections'
}

const RANK: Record<CapabilityState, number> = { down: 3, needs_setup: 2, ready: 1, planned: 0, unsupported: 0 }

export interface ToolHealth {
  readonly ok: boolean
  readonly label: string
  readonly text: string
}

/** A tool's health is the registry's, the same state Settings shows for its connection. Null when no capability carries the tool. */
export function toolHealth(tool: Pick<ToolView, 'id'>, capabilities: readonly CapabilityView[] | undefined, now: Date): ToolHealth | null {
  const carrying = (capabilities ?? []).filter((c) => c.tools.includes(tool.id))
  const worst = carrying.reduce<CapabilityView | null>((found, c) => (found === null || RANK[c.state] > RANK[found.state] ? c : found), null)
  if (worst === null) return null
  if (worst.state === 'down') return { ok: false, label: 'Not working right now', text: [worst.system ? `${worst.system} isn’t answering.` : null, worst.last_ok_at ? `Last seen working ${when(worst.last_ok_at, now)}.` : null].filter(Boolean).join(' ') }
  if (worst.state === 'needs_setup') return { ok: false, label: 'Needs setup', text: worst.fix ? dot(worst.fix) : '' }
  return { ok: true, label: 'Ready', text: worst.last_ok_at ? `Last seen working ${when(worst.last_ok_at, now)}.` : '' }
}

export const NEW_TOOL_WORDS = 'Tools are built by the team. If a workflow needs one that isn’t here, tell whoever looks after the platform, because the team decides on new tools.'
