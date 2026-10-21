import { agentIdentity } from '../ui/agents'
import { agentId, type AgentRegistry } from '../run'

/** The engine's view of src/ui/agents.ts: who hosts the run's agents. */
export const AGENTS: AgentRegistry = {
  host: { id: agentId('room_lead'), display: agentIdentity('room_lead').name },
}
