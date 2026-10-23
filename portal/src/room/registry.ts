import { agentIdentity, KNOWN_AGENT_IDS } from '../ui/agents'
import { agentId, agentNamedIn, doorKey, type AgentRef, type AgentRegistry } from '../run'

const KNOWN: readonly AgentRef[] = KNOWN_AGENT_IDS.map((id) => ({ id: agentId(id), display: agentIdentity(id).name }))

/** The engine's view of src/ui/agents.ts: display names, read doors, and who hosts and troubleshoots. */
export const AGENTS: AgentRegistry = {
  host: { id: agentId('room_lead'), display: agentIdentity('room_lead').name },
  troubleshooter: { id: agentId('troubleshooter'), display: agentIdentity('troubleshooter').name },
  lookup(id) {
    const identity = agentIdentity(id)
    return { display: identity.name, readDoor: identity.readDoor ? doorKey(identity.readDoor) : null }
  },
  named: (words) => agentNamedIn(words, KNOWN),
}

/** Public status pages for read doors, offered next to Retry when that door failed. */
export const STATUS_PAGES: Readonly<Record<string, { readonly label: string; readonly href: string }>> = {
  github: { label: 'Check GitHub status', href: 'https://www.githubstatus.com' },
}
