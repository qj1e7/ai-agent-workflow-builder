import type { FaceState } from '../../ui/AgentFace'
import type { RunStage } from './words'

/** The AI troubleshooter's mood for each stage of a run, as the sketch's TR_FACE: calm at a stop, at work on a retry, pleased once it is moving. */
export const TROUBLE_FACE: Readonly<Record<RunStage, FaceState>> = {
  stopped: 'idle',
  retrying: 'working',
  working: 'working',
  waiting: 'success',
  writing: 'success',
  done: 'success',
  declined: 'idle',
  skipped: 'idle',
}
