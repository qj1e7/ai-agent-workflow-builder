import ended from '@contracts/fixtures/builder/run.n8n.ended.json'
import waiting from '@contracts/fixtures/builder/run.n8n.waiting.json'
import { describe, expect, it } from 'vitest'
import type { RunN8nView } from '../../api/types'
import { edgeKey } from '../../ui/canvasLayout'
import { runCanvasOf } from './n8nStates'

const WAITING = waiting as RunN8nView
const ENDED = ended as RunN8nView

describe('a run drawn on the canvas', () => {
  it('draws a run waiting at the yes: the blocks it passed done, the yes waiting, the rest not run', () => {
    const { nodes, edges } = runCanvasOf(WAITING)
    expect(nodes).toEqual({
      'Mon 8:00': 'idle',
      'Start from the Portal': 'idle',
      'Read release': 'ok',
      Compare: 'ok',
      'Newer?': 'ok',
      'Ask for a yes': 'wait',
      'Create ticket': 'idle',
      'Nothing to change': 'idle',
    })
    expect(edges[edgeKey('Compare', 'Newer?')]).toBe('ok')
    expect(edges[edgeKey('Newer?', 'Ask for a yes')], 'the way to where it waits').toBe('ok')
    expect(edges[edgeKey('Newer?', 'Nothing to change')], 'the way it did not take').toBe('idle')
    expect(edges[edgeKey('Ask for a yes', 'Create ticket')]).toBe('idle')
  })

  it('draws a run that stopped at the write red, and the way into it taken', () => {
    const { nodes, edges } = runCanvasOf(ENDED)
    expect(nodes['Create ticket']).toBe('err')
    expect(nodes['Start from the Portal'], 'n8n’s own record names the start that ran').toBe('ok')
    expect(nodes['Mon 8:00']).toBe('idle')
    expect(edges[edgeKey('Ask for a yes', 'Create ticket')]).toBe('ok')
    expect(edges[edgeKey('Mon 8:00', 'Read release')]).toBe('idle')
  })

  it('flows dashes only into the block at work', () => {
    const { nodes, edges } = runCanvasOf({ ...WAITING, states: { 'Read release': 'done', Compare: 'running' } })
    expect(nodes.Compare).toBe('now')
    expect(edges[edgeKey('Read release', 'Compare')]).toBe('flow')
    expect(Object.values(edges).filter((state) => state === 'flow')).toHaveLength(1)
  })
})
