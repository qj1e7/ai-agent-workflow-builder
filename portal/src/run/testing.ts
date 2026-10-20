import { agentId, doorKey } from './brand'
import type { AgentRegistry } from './room'

/** The registry the tests fold with: the same three known agents as src/ui/agents.ts. */
export const TEST_REGISTRY: AgentRegistry = {
  host: { id: agentId('room_lead'), display: 'Room lead' },
  troubleshooter: { id: agentId('troubleshooter'), display: 'AI troubleshooter' },
  lookup(id) {
    if (id === 'release_checker') return { display: 'Release checker', readDoor: doorKey('github') }
    if (id === 'room_lead') return { display: 'Room lead', readDoor: null }
    if (id === 'troubleshooter') return { display: 'AI troubleshooter', readDoor: null }
    return { display: id, readDoor: null }
  },
}
