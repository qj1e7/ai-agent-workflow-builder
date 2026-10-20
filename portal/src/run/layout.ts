import type { DoorKey } from './brand'
import { seatKeyOf, type Anchor, type FloorPlan, type PlanDoor, type SeatKey } from './room'

export interface Point {
  readonly x: number
  readonly y: number
}

export interface Box {
  readonly x: number
  readonly y: number
  readonly w: number
  readonly h: number
}

export type RoomSize = 'wide' | 'compact'

export type BoxRole =
  | { readonly role: 'seat'; readonly key: SeatKey }
  | { readonly role: 'overflow'; readonly row: 'agents' | 'people'; readonly hidden: readonly SeatKey[] }
  | { readonly role: 'door'; readonly side: PlanDoor['side']; readonly key: DoorKey | 'teams' | null; readonly index: number }
  | { readonly role: 'checker'; readonly door: DoorKey | null }
  | { readonly role: 'table' }
  | { readonly role: 'ticket' }
  | { readonly role: 'table_edge' }
  | { readonly role: 'speech_band' }
  | { readonly role: 'speech'; readonly key: SeatKey }

export interface LayoutBox extends Box {
  readonly who: BoxRole
}

export interface SeatBox {
  /** Avatar, name and status line together. Collision checks use this. */
  readonly box: Box
  readonly avatar: Box
}

export interface OverflowSeat {
  readonly row: 'agents' | 'people'
  readonly seat: SeatBox
  /** In slot order. The component writes "+3 more" and lists names in the accessible label. */
  readonly hidden: readonly SeatKey[]
}

export interface DoorBox {
  readonly side: PlanDoor['side']
  readonly key: DoorKey | 'teams' | null
  readonly label: string | null
  /** The whole reserved area inside the room: the label above the opening and the swing in front of it. */
  readonly box: Box
  /** The name and status text. */
  readonly labelBox: Box
  /** The gap in the wall. For side doors a y-range on the wall's x; for the Teams door an x-range on the floor's bottom. */
  readonly opening: Box
  /** Inside the room, in front of the opening: where a request token parks and where people step in. */
  readonly approach: Point
  /** Write doors only: where the safety checker stands, inside the door. */
  readonly checker: Box | null
  /** Doors this slot stands for beyond capacity. */
  readonly hidden: readonly (DoorKey | null)[]
}

export interface SpeechSlot {
  /** Inside the speech band, clamped to the room. */
  readonly card: Box
  /** x of the tail, over the speaker's avatar centre. */
  readonly tailX: number
}

export interface RoomLayout {
  readonly size: RoomSize
  readonly width: number
  readonly height: number
  readonly wall: number
  readonly floor: Box
  readonly speechBand: Box | null
  readonly table: Box
  readonly ticketSpot: Box
  readonly tableEdge: Box
  /** Shown seats only. A hidden seat resolves to its row's overflow seat through point(). */
  readonly seats: ReadonlyMap<SeatKey, SeatBox>
  readonly overflow: readonly OverflowSeat[]
  readonly doors: readonly DoorBox[]
  /** Wide: one slot per shown agent seat. Compact: empty; speech renders in a fixed slot below the room. */
  readonly speech: ReadonlyMap<SeatKey, SpeechSlot>
  /** Every drawn thing, flat, so the no-collision property is one loop over pairs. */
  readonly boxes: readonly LayoutBox[]
  /** Horizontal travel lanes (y) and wall-side lanes (x) that routes use. */
  readonly lanes: { readonly top: number; readonly bottom: number; readonly left: number; readonly right: number }
  /** Pixel position of any anchor. Total: a hidden seat answers with its overflow seat. */
  point(a: Anchor): Point
  /** Orthogonal polyline from one anchor to another through the lanes, so a travelling object never crosses a label. */
  route(from: Anchor, to: Anchor): readonly Point[]
}

export interface Metrics {
  readonly minWidth: number
  readonly wall: number
  readonly pad: number
  readonly gap: number
  readonly rowGap: number
  readonly lane: number
  readonly avatar: number
  readonly seatW: number
  readonly seatH: number
  readonly band: number
  readonly cardMaxW: number
  readonly tail: number
  readonly doorCol: number
  readonly doorLabelH: number
  readonly doorOpeningH: number
  readonly doorsShown: number
  readonly tableMinH: number
  readonly ticketW: number
  readonly ticketH: number
  readonly teamsW: number
  readonly teamsH: number
  readonly teamsOpeningW: number
}

/** All sizes in CSS px. The room component renders at the measured width, so nothing is scaled. */
export const ROOM_METRICS: Readonly<Record<RoomSize, Metrics>> = {
  wide: {
    minWidth: 640,
    wall: 12,
    pad: 16,
    gap: 8,
    rowGap: 12,
    lane: 20,
    avatar: 56,
    seatW: 128,
    seatH: 100,
    band: 120,
    cardMaxW: 320,
    tail: 8,
    doorCol: 156,
    doorLabelH: 48,
    doorOpeningH: 60,
    doorsShown: 3,
    tableMinH: 160,
    ticketW: 300,
    ticketH: 108,
    teamsW: 168,
    teamsH: 56,
    teamsOpeningW: 56,
  },
  compact: {
    minWidth: 0,
    wall: 8,
    pad: 10,
    gap: 4,
    rowGap: 10,
    lane: 12,
    avatar: 40,
    seatW: 80,
    seatH: 94,
    band: 0,
    cardMaxW: 0,
    tail: 0,
    doorCol: 80,
    doorLabelH: 36,
    doorOpeningH: 52,
    doorsShown: 2,
    tableMinH: 116,
    ticketW: 168,
    ticketH: 96,
    teamsW: 96,
    teamsH: 50,
    teamsOpeningW: 40,
  },
}

const box = (x: number, y: number, w: number, h: number): Box => ({ x, y, w, h })
const centre = (b: Box): Point => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 })

function stack(n: number, m: Metrics): number {
  const doorH = m.doorLabelH + m.doorOpeningH
  return n <= 0 ? 0 : n * doorH + (n - 1) * m.gap
}

interface Row {
  readonly y: number
  readonly shown: { readonly key: SeatKey; readonly x: number }[]
  readonly overflow: { readonly x: number; readonly hidden: SeatKey[] } | null
}

function agentsRow(plan: FloorPlan, floor: Box, y: number, m: Metrics): Row {
  const pitch = m.seatW + m.gap
  const cx = floor.x + floor.w / 2
  const sideCap = Math.max(0, Math.floor((floor.w / 2 - m.pad - m.seatW / 2) / pitch))
  const maxSlot = 2 * sideCap
  const xOf = (slot: number) => cx - m.seatW / 2 + (slot === 0 ? 0 : (slot % 2 === 1 ? -1 : 1) * Math.ceil(slot / 2) * pitch)
  const highest = plan.agents.reduce((top, seat) => Math.max(top, seat.slot), -1)
  const overflowing = highest > maxSlot
  const shown: Row['shown'] = []
  const hidden: SeatKey[] = []
  for (const seat of [...plan.agents].sort((a, b) => a.slot - b.slot)) {
    if (overflowing && seat.slot >= maxSlot) hidden.push(seat.key)
    else shown.push({ key: seat.key, x: xOf(seat.slot) })
  }
  return { y, shown, overflow: overflowing ? { x: xOf(maxSlot), hidden } : null }
}

function peopleRow(plan: FloorPlan, span: Box, y: number, m: Metrics): Row {
  const pitch = m.seatW + m.gap
  const seats = [...plan.people].sort((a, b) => a.slot - b.slot)
  const fits = (from: number) => Math.floor((span.x + span.w - from + m.gap) / pitch)
  // The row starts at the left third when three seats still fit from there, else at the span's left.
  // The start never depends on how many people are seated, so an arrival never shifts anyone.
  const third = span.x + Math.round(span.w / 3) - m.seatW / 2
  const start = third >= span.x && fits(third) >= 3 ? third : span.x
  const capacity = Math.max(1, fits(start))
  const xOf = (slot: number) => start + slot * pitch
  const overflowing = seats.length > capacity
  const shown: Row['shown'] = []
  const hidden: SeatKey[] = []
  for (const seat of seats) {
    if (overflowing && seat.slot >= capacity - 1) hidden.push(seat.key)
    else shown.push({ key: seat.key, x: xOf(seat.slot) })
  }
  return { y, shown, overflow: overflowing ? { x: xOf(capacity - 1), hidden } : null }
}

function seatBox(x: number, y: number, m: Metrics): SeatBox {
  return { box: box(x, y, m.seatW, m.seatH), avatar: box(x + (m.seatW - m.avatar) / 2, y, m.avatar, m.avatar) }
}

function wallDoors(doors: readonly PlanDoor[], side: 'read' | 'write', floor: Box, middle: Box, m: Metrics): DoorBox[] {
  const mine = doors.filter((door) => door.side === side)
  if (mine.length === 0) return []
  const shownCount = Math.min(mine.length, m.doorsShown)
  const doorH = m.doorLabelH + m.doorOpeningH
  const top = middle.y + Math.round((middle.h - stack(shownCount, m)) / 2)
  const x = side === 'read' ? floor.x : floor.x + floor.w - m.doorCol
  const result: DoorBox[] = []
  for (let i = 0; i < shownCount; i += 1) {
    const last = i === shownCount - 1 && mine.length > shownCount
    const door = mine[i] as PlanDoor
    const y = top + i * (doorH + m.gap)
    const whole = box(x, y, m.doorCol, doorH)
    const opening = box(side === 'read' ? floor.x : floor.x + floor.w, y + m.doorLabelH, 0, m.doorOpeningH)
    const approachX = side === 'read' ? floor.x + Math.round(m.doorCol * 0.36) : floor.x + floor.w - Math.round(m.doorCol * 0.36)
    const approach = { x: approachX, y: opening.y + opening.h / 2 }
    const inset = Math.round(m.doorCol * 0.08)
    const checker = side === 'write' ? box(x + inset, opening.y, m.doorCol - 2 * inset, m.doorOpeningH) : null
    const key = last ? null : door.key === 'teams' ? null : door.key
    result.push({
      side,
      key: last ? (door.key === 'teams' ? null : door.key) : key,
      label: door.label,
      box: whole,
      labelBox: box(x, y, m.doorCol, m.doorLabelH),
      opening,
      approach,
      checker,
      hidden: last ? mine.slice(i).map((d) => (d.key === 'teams' ? null : d.key)) : [],
    })
  }
  return result
}

function teamsDoor(floor: Box, m: Metrics): DoorBox {
  const x = floor.x + floor.w - m.pad - m.teamsW
  const y = floor.y + floor.h - m.teamsH
  const whole = box(x, y, m.teamsW, m.teamsH)
  const opening = box(x + m.teamsW - m.teamsOpeningW, floor.y + floor.h, m.teamsOpeningW, 0)
  return {
    side: 'teams',
    key: 'teams',
    label: null,
    box: whole,
    labelBox: box(x, y, m.teamsW - m.teamsOpeningW - m.gap, m.teamsH),
    opening,
    approach: { x: opening.x + opening.w / 2, y: y + Math.round(m.teamsH * 0.3) },
    checker: null,
    hidden: [],
  }
}

function segmentCrosses(a: Point, b: Point, target: Box, pad: number): boolean {
  const left = target.x - pad
  const right = target.x + target.w + pad
  const top = target.y - pad
  const bottom = target.y + target.h + pad
  const minX = Math.min(a.x, b.x)
  const maxX = Math.max(a.x, b.x)
  const minY = Math.min(a.y, b.y)
  const maxY = Math.max(a.y, b.y)
  return minX < right && maxX > left && minY < bottom && maxY > top
}

function contains(outer: Box, inner: Box): boolean {
  return inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.w <= outer.x + outer.w && inner.y + inner.h <= outer.y + outer.h
}

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

function solid(role: BoxRole['role']): boolean {
  return role === 'seat' || role === 'overflow' || role === 'door' || role === 'table' || role === 'checker'
}

/** Pairs of boxes that must not overlap but do. Exported for the tests and a dev overlay. */
export function collisions(layout: RoomLayout): readonly [LayoutBox, LayoutBox][] {
  const bad: [LayoutBox, LayoutBox][] = []
  const boxes = layout.boxes
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i] as LayoutBox
      const b = boxes[j] as LayoutBox
      if (!intersects(a, b)) continue
      if (allowed(a, b) || allowed(b, a)) continue
      bad.push([a, b])
    }
  }
  return bad
}

function allowed(a: LayoutBox, b: LayoutBox): boolean {
  const r = a.who.role
  const s = b.who.role
  if ((r === 'ticket' || r === 'table_edge') && s === 'table') return contains(b, a)
  if (r === 'ticket' && s === 'table_edge') return true
  if (r === 'checker' && s === 'door') return contains(b, a)
  if (r === 'speech' && s === 'speech_band') return contains(b, a)
  if (r === 'speech' && s === 'speech') return true
  return false
}

/**
 * Solid boxes a route crosses, other than the boxes its two ends live in. A seat's name and status
 * (the box below its avatar) count even for the seat the route starts or ends at.
 */
export function routeCrossings(layout: RoomLayout, from: Anchor, to: Anchor): readonly LayoutBox[] {
  const path = layout.route(from, to)
  const start = layout.point(from)
  const end = layout.point(to)
  const own = (b: LayoutBox) => pointIn(start, b, 1) || pointIn(end, b, 1)
  const crosses = (b: Box) => {
    for (let i = 1; i < path.length; i += 1) if (segmentCrosses(path[i - 1] as Point, path[i] as Point, b, 0)) return true
    return false
  }
  const crossed: LayoutBox[] = []
  for (const b of layout.boxes) {
    if (!solid(b.who.role) || b.who.role === 'table') continue
    if (own(b)) {
      if (b.who.role !== 'seat' && b.who.role !== 'overflow') continue
      const seat = b.who.role === 'seat' ? layout.seats.get(b.who.key) : layout.overflow.find((o) => o.row === (b.who as { row: 'agents' | 'people' }).row)?.seat
      if (!seat) continue
      const label: Box = { x: b.x, y: seat.avatar.y + seat.avatar.h, w: b.w, h: b.y + b.h - (seat.avatar.y + seat.avatar.h) }
      if (crosses(label)) crossed.push(b)
      continue
    }
    if (crosses(b)) crossed.push(b)
  }
  return crossed
}

function pointIn(p: Point, b: Box, pad: number): boolean {
  return p.x >= b.x - pad && p.x <= b.x + b.w + pad && p.y >= b.y - pad && p.y <= b.y + b.h + pad
}

/**
 * Every position in the room from the plan and the width. Nothing is hand-placed.
 *
 * Invariants (tested by enumeration):
 * - no two of seats, overflow seats, doors, checkers, table and the Teams door overlap
 * - all of them sit inside the floor; the speech band holds only speech cards; the table holds only the ticket
 * - adding an agent or a step never moves an already shown seat (until that seat itself goes to overflow)
 */
export function layoutRoom(plan: FloorPlan, width: number): RoomLayout {
  const size: RoomSize = width >= ROOM_METRICS.wide.minWidth ? 'wide' : 'compact'
  const m = ROOM_METRICS[size]
  const floorX = m.wall
  const floorW = width - 2 * m.wall
  const readCount = plan.doors.filter((door) => door.side === 'read').length
  const writeCount = plan.doors.filter((door) => door.side === 'write').length
  const doorsOnAWall = Math.min(m.doorsShown, Math.max(2, readCount, writeCount))
  const middleH = Math.max(m.tableMinH, stack(doorsOnAWall, m))

  const bandTop = m.wall
  const agentsTop = bandTop + m.band
  const middleTop = agentsTop + m.seatH + m.rowGap
  const peopleTop = middleTop + middleH + m.rowGap
  const floorH = peopleTop + m.seatH + m.pad - m.wall
  const height = floorH + 2 * m.wall
  const floor = box(floorX, m.wall, floorW, floorH)
  const speechBand = m.band > 0 ? box(floor.x, bandTop, floor.w, m.band) : null
  const middle = box(floor.x, middleTop, floor.w, middleH)

  const teams = teamsDoor(floor, m)
  const reads = wallDoors(plan.doors, 'read', floor, middle, m)
  const writes = wallDoors(plan.doors, 'write', floor, middle, m)
  const doors = [teams, ...reads, ...writes]

  const tableX = floor.x + m.doorCol + m.lane
  const table = box(tableX, middle.y, floor.w - 2 * (m.doorCol + m.lane), middle.h)
  const ticketW = Math.min(m.ticketW, table.w - 2 * m.gap)
  const ticketH = Math.min(m.ticketH, table.h - 2 * m.gap)
  const ticketSpot = box(table.x + (table.w - ticketW) / 2, table.y + (table.h - ticketH) / 2, ticketW, ticketH)
  const edgeW = Math.min(ticketW, Math.max(0, table.w - ticketW / 2 - m.gap))
  const tableEdge = box(table.x + table.w - edgeW - m.gap, ticketSpot.y, edgeW, ticketH)

  const agents = agentsRow(plan, floor, agentsTop, m)
  const peopleSpan = box(floor.x + m.pad, peopleTop, teams.box.x - m.gap - (floor.x + m.pad), m.seatH)
  const people = peopleRow(plan, peopleSpan, peopleTop, m)

  const seats = new Map<SeatKey, SeatBox>()
  const boxes: LayoutBox[] = []
  const overflow: OverflowSeat[] = []
  for (const row of [agents, people]) {
    for (const seat of row.shown) {
      const placed = seatBox(seat.x, row.y, m)
      seats.set(seat.key, placed)
      boxes.push({ ...placed.box, who: { role: 'seat', key: seat.key } })
    }
    if (row.overflow) {
      const placed = seatBox(row.overflow.x, row.y, m)
      const which = row === agents ? 'agents' : 'people'
      overflow.push({ row: which, seat: placed, hidden: row.overflow.hidden })
      boxes.push({ ...placed.box, who: { role: 'overflow', row: which, hidden: row.overflow.hidden } })
    }
  }
  doors.forEach((door, index) => {
    boxes.push({ ...door.box, who: { role: 'door', side: door.side, key: door.key, index } })
    if (door.checker) boxes.push({ ...door.checker, who: { role: 'checker', door: door.key === 'teams' ? null : door.key } })
  })
  boxes.push({ ...table, who: { role: 'table' } })
  boxes.push({ ...ticketSpot, who: { role: 'ticket' } })
  boxes.push({ ...tableEdge, who: { role: 'table_edge' } })

  const speech = new Map<SeatKey, SpeechSlot>()
  if (speechBand) {
    boxes.push({ ...speechBand, who: { role: 'speech_band' } })
    const cardW = Math.min(m.cardMaxW, floor.w - 2 * m.pad)
    const cardH = speechBand.h - m.tail - m.gap
    for (const seat of agents.shown) {
      const avatarCx = seat.x + m.seatW / 2
      const x = Math.max(floor.x + m.pad, Math.min(floor.x + floor.w - m.pad - cardW, avatarCx - cardW / 2))
      const card = box(x, speechBand.y + m.gap, cardW, cardH)
      speech.set(seat.key, { card, tailX: avatarCx })
      boxes.push({ ...card, who: { role: 'speech', key: seat.key } })
    }
  }

  const lanes = {
    top: agentsTop + m.seatH + m.rowGap / 2,
    bottom: middleTop + middleH + m.rowGap / 2,
    left: floor.x + m.doorCol + m.lane / 2,
    right: floor.x + floor.w - m.doorCol - m.lane / 2,
  }

  const overflowFor = (key: SeatKey) => overflow.find((seat) => seat.hidden.includes(key))
  const doorOf = (key: DoorKey) => doors.find((door) => door.key === key) ?? doors.find((door) => door.hidden.includes(key))

  function seatPoint(key: SeatKey): Point {
    const shown = seats.get(key)
    if (shown) return centre(shown.avatar)
    const hidden = overflowFor(key)
    if (hidden) return centre(hidden.seat.avatar)
    return centre(table)
  }

  function point(a: Anchor): Point {
    switch (a.at) {
      case 'agent':
      case 'starter':
      case 'step':
        return seatPoint(seatKeyOf(a) as SeatKey)
      case 'door':
        return doorOf(a.key)?.approach ?? centre(table)
      case 'teams':
        return teams.approach
      case 'table':
        return centre(ticketSpot)
      case 'table_edge':
        return centre(tableEdge)
    }
  }

  type Zone = 'agents' | 'people' | 'read' | 'write' | 'teams' | 'table'

  function zoneOf(a: Anchor): Zone {
    switch (a.at) {
      case 'agent':
        return 'agents'
      case 'starter':
      case 'step':
        return 'people'
      case 'door': {
        const door = doorOf(a.key)
        return door?.side === 'write' ? 'write' : door?.side === 'read' ? 'read' : 'table'
      }
      case 'teams':
        return 'teams'
      case 'table':
      case 'table_edge':
        return 'table'
    }
  }

  function seatBoxOf(a: Anchor): Box | null {
    const key = seatKeyOf(a)
    if (!key) return null
    const shown = seats.get(key)
    if (shown) return shown.box
    return overflowFor(key)?.seat.box ?? null
  }

  /**
   * The lane a zone exits into. A seat leaves sideways through the gutter beside it (towards the other end),
   * so a path never crosses its own name and status; doors exit into their wall lane.
   */
  function exitOf(a: Anchor, p: Point, towards: Point): Point[] {
    switch (zoneOf(a)) {
      case 'agents':
      case 'people': {
        const lane = zoneOf(a) === 'agents' ? lanes.top : lanes.bottom
        const seat = seatBoxOf(a)
        if (!seat) return [{ x: p.x, y: lane }]
        const gutter = towards.x >= p.x ? seat.x + seat.w + m.gap / 2 : seat.x - m.gap / 2
        return [
          { x: gutter, y: p.y },
          { x: gutter, y: lane },
        ]
      }
      case 'read':
        return [{ x: lanes.left, y: p.y }]
      case 'write':
        return [{ x: lanes.right, y: p.y }]
      case 'teams':
        return [{ x: p.x, y: lanes.bottom }]
      case 'table':
        return []
    }
  }

  function route(from: Anchor, to: Anchor): readonly Point[] {
    const a = point(from)
    const b = point(to)
    const za = zoneOf(from)
    const zb = zoneOf(to)
    if (za === 'table' && zb === 'table') return [a, b]
    const out = exitOf(from, a, b)
    const back = exitOf(to, b, a).reverse()
    const first = out[out.length - 1] ?? a
    const last = back[0] ?? b
    const middleWay: Point[] = []
    const horizontal = (p: Point, q: Point) => p.y === q.y
    const vertical = (p: Point, q: Point) => p.x === q.x
    if (za === 'table' || zb === 'table') {
      const tableSide = za === 'table' ? a : b
      const laneSide = za === 'table' ? last : first
      const corner: Point =
        laneSide.y === lanes.top || laneSide.y === lanes.bottom
          ? { x: tableSide.x, y: laneSide.y }
          : { x: laneSide.x, y: tableSide.y }
      return za === 'table' ? [a, corner, ...back, b] : [a, ...out, corner, b]
    }
    if (!horizontal(first, last) && !vertical(first, last)) {
      const onRow = (p: Point) => p.y === lanes.top || p.y === lanes.bottom
      if (onRow(first) && onRow(last)) {
        const laneX = first.x < last.x ? lanes.left : lanes.right
        const laneX2 = Math.abs(first.x - laneX) + Math.abs(last.x - laneX) <= Math.abs(first.x - lanes.right) + Math.abs(last.x - lanes.right) ? laneX : lanes.right
        middleWay.push({ x: laneX2, y: first.y }, { x: laneX2, y: last.y })
      } else if (onRow(first)) {
        middleWay.push({ x: last.x, y: first.y })
      } else {
        middleWay.push({ x: first.x, y: last.y })
      }
    }
    return [a, ...out, ...middleWay, ...back, b]
  }

  return {
    size,
    width,
    height,
    wall: m.wall,
    floor,
    speechBand,
    table,
    ticketSpot,
    tableEdge,
    seats,
    overflow,
    doors,
    speech,
    boxes,
    lanes,
    point,
    route,
  }
}
