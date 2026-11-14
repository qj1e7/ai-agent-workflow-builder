import type { N8nBlockKind, N8nBlockView } from '../api/types'

/** A block not built yet, built, the step a test run is at, one it reached, or the yes the safety checker added. */
export type NodeState = 'off' | 'idle' | 'now' | 'ok' | 'added'
/** A way out not built yet, built, the test run flowing along it, or one it took. */
export type EdgeState = 'off' | 'idle' | 'flow' | 'ok'

export const edgeKey = (from: string, to: string): string => `${from}->${to}`

export const NODE = 84
const COL = 175
const ROW = 150
const PAD_X = 40
const PAD_TOP = 16
const LABELS = 50

export interface PlacedNode {
  readonly name: string
  readonly kind: N8nBlockKind
  readonly col: number
  readonly row: number
  /** The box's top left corner. */
  readonly x: number
  readonly y: number
  /** One of the platform's own blocks, which every write goes through, rather than one of n8n's. */
  readonly ours: boolean
}

export interface PlacedEdge {
  readonly from: string
  readonly to: string
  /** An IF's true or false. Other ways out are not named on the line. */
  readonly label: string | null
  readonly path: string
  readonly labelAt: { readonly x: number; readonly y: number }
}

export interface Laid {
  readonly nodes: readonly PlacedNode[]
  readonly edges: readonly PlacedEdge[]
  readonly width: number
  readonly height: number
}

const STARTS: ReadonlySet<N8nBlockKind> = new Set(['schedule', 'start', 'manual', 'error'])
/** The node pack's blocks (ADR 0027). Every other block is one of n8n's own. */
const OURS: ReadonlySet<N8nBlockKind> = new Set(['read', 'agent', 'propose', 'ask', 'write', 'tell', 'report'])

/**
 * Columns and rows for the blocks: the blocks that start a run in the first column, each other block one column after the first
 * block that leads to it, a block's first way out on its own row and any other way out on the next free row below. A block no
 * way out reaches goes after the rest.
 */
export function layOut(blocks: readonly N8nBlockView[]): Laid {
  const byName = new Map(blocks.map((block) => [block.name, block]))
  const placed = new Map<string, { col: number; row: number }>()
  const taken = new Map<number, Set<number>>()
  const place = (name: string, col: number, wanted: number) => {
    const rows = taken.get(col) ?? new Set<number>()
    let row = wanted
    while (rows.has(row)) row += 1
    rows.add(row)
    taken.set(col, rows)
    placed.set(name, { col, row })
  }
  const queue: string[] = []
  for (const block of blocks.filter((one) => STARTS.has(one.kind))) {
    place(block.name, 0, 0)
    queue.push(block.name)
  }
  const visit = () => {
    for (let at = 0; at < queue.length; at += 1) {
      const name = queue[at] ?? ''
      const from = placed.get(name)
      if (!from) continue
      byName.get(name)?.next.forEach((exit, index) => {
        if (placed.has(exit.to) || !byName.has(exit.to)) return
        place(exit.to, from.col + 1, from.row + (index === 0 ? 0 : 1))
        queue.push(exit.to)
      })
    }
  }
  visit()
  const lastCol = () => Math.max(-1, ...[...placed.values()].map((spot) => spot.col))
  for (const block of blocks) {
    if (placed.has(block.name)) continue
    place(block.name, lastCol() + 1, 0)
    queue.push(block.name)
    visit()
  }
  const nodes = blocks.map((block): PlacedNode => {
    const { col, row } = placed.get(block.name) ?? { col: 0, row: 0 }
    return { name: block.name, kind: block.kind, col, row, x: PAD_X + col * COL, y: PAD_TOP + row * ROW, ours: OURS.has(block.kind) }
  })
  const nodeOf = new Map(nodes.map((node) => [node.name, node]))
  const edges = blocks.flatMap((block) =>
    block.next.flatMap((exit): PlacedEdge[] => {
      const a = nodeOf.get(block.name)
      const b = nodeOf.get(exit.to)
      if (!a || !b) return []
      const x1 = a.x + NODE
      const y1 = a.y + NODE / 2
      const x2 = b.x
      const y2 = b.y + NODE / 2
      const label = block.kind === 'branch' ? exit.exit : null
      return [{ from: block.name, to: exit.to, label, path: `M${x1} ${y1} C${x1 + 50} ${y1}, ${x2 - 50} ${y2}, ${x2} ${y2}`, labelAt: { x: x1 + 8, y: y2 > y1 ? y1 + 24 : y1 - 9 } }]
    }),
  )
  const cols = Math.max(...nodes.map((node) => node.col), 0) + 1
  const rows = Math.max(...nodes.map((node) => node.row), 0) + 1
  return { nodes, edges, width: PAD_X * 2 + (cols - 1) * COL + NODE + 40, height: PAD_TOP + (rows - 1) * ROW + NODE + LABELS }
}
