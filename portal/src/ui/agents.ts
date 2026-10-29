import { pickStable } from './pickStable'

export type Accessory = 'headset' | 'magnifier' | 'wrench' | 'none'

export interface AgentIdentity {
  readonly id: string
  readonly name: string
  readonly accessory: Accessory
  /** A CSS colour for the accessory, the acting ring and the name beside the face. It follows the theme. */
  readonly hue: string
  /** A CSS colour for the head. It stays light in both themes. */
  readonly tint: string
}

interface Colours {
  readonly hue: string
  readonly tint: string
}

const known: Readonly<Record<string, Omit<AgentIdentity, 'id'>>> = {
  planner: {
    name: 'Planner',
    accessory: 'headset',
    hue: 'var(--lead)',
    tint: 'var(--lead-tint)',
  },
  version_checker: {
    name: 'Version checker',
    accessory: 'magnifier',
    hue: 'var(--checker)',
    tint: 'var(--checker-tint)',
  },
  troubleshooter: {
    name: 'AI troubleshooter',
    accessory: 'wrench',
    hue: 'var(--trouble)',
    tint: 'var(--trouble-tint)',
  },
}

export const KNOWN_AGENT_IDS: readonly string[] = Object.keys(known)

const OTHER_AGENT_COLOURS: readonly [Colours, ...Colours[]] = [
  { hue: 'var(--agent-1)', tint: 'var(--agent-1-tint)' },
  { hue: 'var(--agent-2)', tint: 'var(--agent-2-tint)' },
  { hue: 'var(--agent-3)', tint: 'var(--agent-3-tint)' },
  { hue: 'var(--agent-4)', tint: 'var(--agent-4-tint)' },
]

function sentenceCase(id: string): string {
  const spaced = id.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/**
 * Every agent has a face. A known agent has its own accessory and colours. Any other id gets a plain face in one of
 * the fixed agent colours, chosen from the id, so it looks the same on every screen and in every run.
 */
export function agentIdentity(id: string, display?: string): AgentIdentity {
  const registered = known[id]
  if (registered) return { id, ...registered }
  return {
    id,
    name: display ?? sentenceCase(id),
    accessory: 'none',
    ...pickStable(OTHER_AGENT_COLOURS, id),
  }
}
