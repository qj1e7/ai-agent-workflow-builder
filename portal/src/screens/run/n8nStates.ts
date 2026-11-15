import type { N8nRunState, RunN8nView } from '../../api/types'
import { edgeKey, type CanvasState, type EdgeState, type NodeState } from '../../ui/canvasLayout'

/** A block's state as the platform names it, drawn as the sketch's live canvas draws it. */
const DRAWN: Readonly<Record<N8nRunState, NodeState>> = { running: 'now', waiting: 'wait', done: 'ok', failed: 'err' }

const REACHED: ReadonlySet<NodeState> = new Set(['ok', 'now', 'wait', 'err'])

/**
 * The canvas of a run: each block in its state, a block not named not run yet. A way out the run took is green; dashes flow along
 * the one into the block at work, so the canvas shows where the run is and where it stopped.
 */
export function runCanvasOf({ blocks, states }: Pick<RunN8nView, 'blocks' | 'states'>): CanvasState {
  const nodes: Record<string, NodeState> = {}
  for (const block of blocks) {
    const state = states[block.name]
    nodes[block.name] = state ? DRAWN[state] : 'idle'
  }
  const edges: Record<string, EdgeState> = {}
  for (const block of blocks) {
    for (const exit of block.next) {
      const to = nodes[exit.to] ?? 'idle'
      edges[edgeKey(block.name, exit.to)] = nodes[block.name] !== 'ok' ? 'idle' : to === 'now' ? 'flow' : REACHED.has(to) ? 'ok' : 'idle'
    }
  }
  return { nodes, edges }
}
