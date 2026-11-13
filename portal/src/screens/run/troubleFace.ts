import type { FaceState } from '../../ui/AgentFace'
import type { RunState } from './words'

/** The AI troubleshooter's mood for each state of a run, as the sketch's TR_FACE: calm at a stop, at work on a retry, pleased once it is moving. */
export const TROUBLE_FACE: Readonly<Record<RunState, FaceState>> = {
  failed: 'idle',
  pending: 'working',
  working: 'working',
  proposed: 'working',
  awaiting_approval: 'success',
  acting: 'success',
  succeeded: 'success',
  rejected: 'idle',
  skipped: 'idle',
  expired: 'idle',
  lost: 'idle',
}
