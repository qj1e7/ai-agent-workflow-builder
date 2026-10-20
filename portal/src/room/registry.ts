import { agentIdentity } from '../ui/agents'
import { agentId, doorKey, type AgentRegistry } from '../run'

/** The engine's view of src/ui/agents.ts: display names, read doors, and who hosts and troubleshoots. */
export const AGENTS: AgentRegistry = {
  host: { id: agentId('room_lead'), display: agentIdentity('room_lead').name },
  troubleshooter: { id: agentId('troubleshooter'), display: agentIdentity('troubleshooter').name },
  lookup(id) {
    const identity = agentIdentity(id)
    return { display: identity.name, readDoor: identity.readDoor ? doorKey(identity.readDoor) : null }
  },
}

/** Public status pages for read doors, offered next to Retry when that door failed. */
export const STATUS_PAGES: Readonly<Record<string, { readonly label: string; readonly href: string }>> = {
  github: { label: 'Check GitHub status', href: 'https://www.githubstatus.com' },
}
