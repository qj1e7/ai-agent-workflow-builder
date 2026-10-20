import { GlyphChecker, GlyphLead, GlyphPlatform, GlyphTrouble, type Icon } from './icons'

export type ReadDoor = 'github'

export interface AgentIdentity {
  readonly id: string
  readonly name: string
  readonly glyph: Icon
  readonly hue: string
  readonly readDoor?: ReadDoor
}

const known: Readonly<Record<string, Omit<AgentIdentity, 'id'>>> = {
  room_lead: { name: 'Room lead', glyph: GlyphLead, hue: 'var(--lead)' },
  release_checker: { name: 'Release checker', glyph: GlyphChecker, hue: 'var(--checker)', readDoor: 'github' },
  troubleshooter: { name: 'AI troubleshooter', glyph: GlyphTrouble, hue: 'var(--trouble)' },
}

/** The agents the Portal knows by name, for seating a template's cast before any run. */
export const KNOWN_AGENT_IDS: readonly string[] = Object.keys(known)

const OTHER_HUES = ['var(--agent-1)', 'var(--agent-2)', 'var(--agent-3)', 'var(--agent-4)'] as const

function stableHash(text: string): number {
  let hash = 5381
  for (const char of text) hash = (Math.imul(hash, 33) + (char.codePointAt(0) ?? 0)) >>> 0
  return hash
}

function sentenceCase(id: string): string {
  const spaced = id.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function agentIdentity(id: string, display?: string): AgentIdentity {
  const registered = known[id]
  if (registered) return { id, ...registered }
  return {
    id,
    name: display ?? sentenceCase(id),
    glyph: GlyphPlatform,
    hue: OTHER_HUES[stableHash(id) % OTHER_HUES.length] ?? OTHER_HUES[0],
  }
}
