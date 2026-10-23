export interface Point {
  readonly x: number
  readonly y: number
}

export interface Box {
  readonly left: number
  readonly top: number
  readonly width: number
  readonly height: number
}

export type Orientation = 'horizontal' | 'vertical'

/** How far above the gate's node the parcel waits on the phone, so it stands before the barrier. */
const GATE_GAP_VERTICAL = 46

/** Where the break sits past the failed node, at most, along the line. */
export const BREAK_GAP: Readonly<Record<Orientation, number>> = { horizontal: 112, vertical: 44 }

const RAIL: Readonly<Record<Orientation, number>> = { horizontal: 8, vertical: 6 }

/** The 760 px breakpoint lives in CSS only. The line reads its orientation back from where the nodes landed. */
export function orientationOf(nodes: readonly Point[]): Orientation {
  const [a, b] = nodes
  return a && b && Math.abs(b.x - a.x) > Math.abs(b.y - a.y) ? 'horizontal' : 'vertical'
}

function along(o: Orientation, p: Point): number {
  return o === 'horizontal' ? p.x : p.y
}

/** A parcel on its node stays this much narrower than its column. */
const PARCEL_INSET = 16
/** In front of the barrier the parcel stands between two nodes: it clears the node before (13 px) and the arm (9 px) by 4 px. */
const WAIT_INSET = 34

/** The widest the parcel may be at 1440 before it takes its compact form. */
export function parcelRoom(column: number, before: boolean): number {
  return column - (before ? WAIT_INSET : PARCEL_INSET)
}

/** On its node, or in front of the barrier: at 1440 halfway from the stop before, so the wait point scales with the column. */
export function parcelPoint(nodes: readonly Point[], o: Orientation, at: number, before: boolean): Point | null {
  const node = nodes[at]
  if (!node) return null
  if (!before) return node
  if (o === 'vertical') return { x: node.x, y: node.y - GATE_GAP_VERTICAL }
  const previous = nodes[at - 1] ?? node
  return { x: (previous.x + node.x) / 2, y: node.y }
}

/** From the first node to the last, centred on the line. */
export function railBox(nodes: readonly Point[], o: Orientation): Box | null {
  const first = nodes[0]
  const last = nodes.at(-1)
  if (!first || !last) return null
  const t = RAIL[o]
  return o === 'horizontal'
    ? { left: first.x, top: first.y - t / 2, width: last.x - first.x, height: t }
    : { left: first.x - t / 2, top: first.y, width: t, height: last.y - first.y }
}

/** How much of the rail the filled line covers so it ends at the point: 0 at the first node, 1 at the last. */
export function fillScale(nodes: readonly Point[], o: Orientation, point: Point | null): number {
  const first = nodes[0]
  const last = nodes.at(-1)
  if (!first || !last || !point) return 0
  const length = along(o, last) - along(o, first)
  if (length <= 0) return 0
  return Math.min(1, Math.max(0, (along(o, point) - along(o, first)) / length))
}

/** Keeps the break this far short of the next node. */
const BREAK_CLEARANCE = 30

/** Just past the failed node: BREAK_GAP along the line, pulled back when the next node is close. */
export function breakPoint(nodes: readonly Point[], o: Orientation, stop: number): Point | null {
  const node = nodes[stop]
  if (!node) return null
  const next = nodes[stop + 1]
  const room = next ? along(o, next) - along(o, node) - BREAK_CLEARANCE : Infinity
  const step = Math.min(BREAK_GAP[o], room)
  return o === 'horizontal' ? { x: node.x + step, y: node.y } : { x: node.x, y: node.y + step }
}

/** The left edge that centres a box of this width on `centre`, kept between `min` and `max - width`. */
export function clampLeft(centre: number, width: number, min: number, max: number): number {
  const wanted = centre - width / 2
  return Math.max(min, Math.min(wanted, max - width))
}
