import type { FaceState } from '../../ui/AgentFace'
import { fixEnd, type FixState } from './runModel'
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

/** The AI troubleshooter's face under a stop. While it works on a fix it is at work, pleased once a fix is ready, and calm again when it hands back. */
export function troubleFaceOf(state: RunState, fix: FixState | null, now: number): FaceState {
  if (fix === null) return TROUBLE_FACE[state]
  const end = fixEnd(fix, now)
  if (end === null) return 'working'
  return end === 'proposed' ? 'success' : 'idle'
}
