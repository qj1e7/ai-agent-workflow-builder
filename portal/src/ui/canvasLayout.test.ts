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
    expect(at('Ask for a yes')).toEqual([4, 0])
    expect(at('Create ticket')).toEqual([5, 0])
  })

  it('puts a branch’s other way out on the row below, and draws each way out once, naming an IF’s true and false', () => {
    expect(at('Nothing to change')).toEqual([4, 1])
    expect(laid.edges).toHaveLength(BLOCKS.reduce((sum, block) => sum + block.next.length, 0))
    expect(laid.edges.filter((edge) => edge.label !== null).map((edge) => edge.label)).toEqual(['true', 'false'])
  })

  it('marks our blocks, and only ours', () => {
    expect(laid.nodes.filter((node) => node.ours).map((node) => node.name)).toEqual(['Read release', 'Compare', 'Ask for a yes', 'Create ticket'])
  })

  it('draws every block, even one no way out leads to, and sizes itself to hold them', () => {
    const lone = layOut([...BLOCKS, { name: 'Sticky', kind: 'other', next: [] }])
    expect(lone.nodes.map((node) => node.name)).toContain('Sticky')
    expect(lone.width, 'a block no way out reaches goes after the rest').toBeGreaterThan(laid.width)
    for (const node of laid.nodes) expect(node.x + 84 <= laid.width && node.y + 84 <= laid.height, `${node.name} fits`).toBe(true)
  })
})
