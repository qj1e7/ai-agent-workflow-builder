import created from '@contracts/fixtures/builder/agent-use-case.off.created.json'
import { describe, expect, it } from 'vitest'
import type { N8nBlockView } from '../api/types'
import { layOut } from './canvasLayout'

const BLOCKS = created.blocks as N8nBlockView[]

describe('the canvas laid out from the workflow’s blocks', () => {
  const laid = layOut(BLOCKS)
  const at = (name: string) => {
    const node = laid.nodes.find((one) => one.name === name)
    return node ? [node.col, node.row] : null
  }

  it('puts the blocks that start a run first, then each block one column after the block that leads to it, in the order a run meets them', () => {
    expect(at('Mon 8:00')).toEqual([0, 0])
    expect(at('Start from the Portal')).toEqual([0, 1])
    expect(at('Read release')).toEqual([1, 0])
    expect(at('Compare')).toEqual([2, 0])
    expect(at('Newer?')).toEqual([3, 0])
    expect(at('Ask for approval')).toEqual([4, 0])
    expect(at('Create ticket')).toEqual([5, 0])
  })

  it('puts a branch’s other way out on the row below, and draws each way out once, naming an IF’s true and false', () => {
    expect(at('Nothing to change')).toEqual([4, 1])
    expect(laid.edges).toHaveLength(BLOCKS.reduce((sum, block) => sum + block.next.length, 0))
    expect(laid.edges.filter((edge) => edge.label !== null).map((edge) => edge.label)).toEqual(['true', 'false'])
  })

  it('marks our blocks, and only ours', () => {
    expect(laid.nodes.filter((node) => node.ours).map((node) => node.name)).toEqual(['Read release', 'Compare', 'Ask for approval', 'Create ticket'])
  })

  it('draws every block, even one no way out leads to, and sizes itself to hold them', () => {
    const lone = layOut([...BLOCKS, { name: 'Sticky', kind: 'other', badge: 'n8n', next: [] }])
    expect(lone.nodes.map((node) => node.name)).toContain('Sticky')
    expect(lone.width, 'a block no way out reaches goes after the rest').toBeGreaterThan(laid.width)
    for (const node of laid.nodes) expect(node.x + 84 <= laid.width && node.y + 84 <= laid.height, `${node.name} fits`).toBe(true)
  })

  it('draws a way out to a block below in the same column around the right, clear of the block’s own name', () => {
    const ask = laid.nodes.find((node) => node.name === 'Ask for approval')
    const edge = laid.edges.find((one) => one.from === 'Ask for approval' && one.to === 'Nothing to change')
    if (!ask || !edge) throw new Error('the fixture has Ask for approval and its way to Nothing to change')
    const [x0, y0, cx1, cy1, cx2, cy2, x3, y3] = (edge.path.match(/-?\d+(\.\d+)?/g) ?? []).map(Number) as [number, number, number, number, number, number, number, number]
    const at = (t: number) => {
      const u = 1 - t
      return { x: u ** 3 * x0 + 3 * u * u * t * cx1 + 3 * u * t * t * cx2 + t ** 3 * x3, y: u ** 3 * y0 + 3 * u * u * t * cy1 + 3 * u * t * t * cy2 + t ** 3 * y3 }
    }
    // The name and the kind sit under the box, centred, up to 60 px either side of its middle.
    const next = laid.nodes.find((node) => node.col === ask.col + 1 && node.row === ask.row)
    const labels = { top: ask.y + 84, bottom: ask.y + 84 + 44, right: ask.x + 42 + 60, nextLeft: (next?.x ?? Infinity) + 42 - 60 }
    for (let t = 0; t <= 1; t += 0.02) {
      const point = at(t)
      if (point.y < labels.top || point.y > labels.bottom) continue
      expect(point.x, `at t=${t.toFixed(2)}, past Ask for approval’s name`).toBeGreaterThan(labels.right)
      expect(point.x, `at t=${t.toFixed(2)}, short of ${next?.name ?? 'the next'}’s name`).toBeLessThan(labels.nextLeft)
    }
  })
})
