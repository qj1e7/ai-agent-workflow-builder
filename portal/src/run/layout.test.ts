import { describe, expect, it } from 'vitest'
import { agentId, doorKey } from './brand'
import { collisions, laneViolations, layoutRoom, ROOM_METRICS, routeCrossings, segmentCrosses, type Box, type Point, type RoomLayout } from './layout'
import { agentSeatKey, seatKeyOf, stepSeatKey, type Anchor, type FloorPlan, type PlanDoor, type SeatKey } from './room'

const WIDTHS = [320, 358, 390, 640, 760, 960, 1100, 1440] as const
const READ_DOORS = [0, 1, 2, 3, 6] as const
const WRITE_DOORS = [0, 1, 3, 6] as const

function plan(agents: number, steps: number, read: number, write: number, seeded = 0): FloorPlan {
  const doors: PlanDoor[] = [{ side: 'teams', key: 'teams', label: null }]
  for (let i = 0; i < read; i += 1) doors.push({ side: 'read', key: doorKey(`read_${i}`), label: null })
  for (let i = 0; i < write; i += 1) {
    doors.push(i < seeded ? { side: 'write', key: null, label: `Write ${i}` } : { side: 'write', key: doorKey(`write_${i}`), label: null })
  }
  return {
    agents: Array.from({ length: agents }, (_, i) => ({ key: agentSeatKey(agentId(`a${i}`)), slot: i })),
    people: [{ key: 'starter', slot: 0 }, ...Array.from({ length: steps }, (_, i) => ({ key: stepSeatKey(i), slot: i + 1 }))],
    doors,
  }
}

function inside(box: Box, floor: Box): boolean {
  return box.x >= floor.x && box.y >= floor.y && box.x + box.w <= floor.x + floor.w && box.y + box.h <= floor.y + floor.h
}

describe('layoutRoom over every participant count', () => {
  it('never collides, never leaves the floor, keeps the speech band and table clean, keeps every lane wider than the token plus 8 px and clear', () => {
    let checked = 0
    for (const width of WIDTHS) {
      for (let agents = 0; agents <= 30; agents += 1) {
        for (let steps = 0; steps <= 10; steps += 1) {
          for (const read of READ_DOORS) {
            for (const write of WRITE_DOORS) {
              const layout = layoutRoom(plan(agents, steps, read, write), width)
              const where = `width ${width}, ${agents} agents, ${steps} steps, ${read} read, ${write} write`
              const bad = collisions(layout)
              if (bad.length > 0) {
                throw new Error(`${bad.length} collisions at ${where}: ${JSON.stringify(bad[0])}`)
              }
              for (const box of layout.boxes) {
                if (!inside(box, layout.floor)) {
                  throw new Error(`${box.who.role} leaves the floor at ${where}`)
                }
              }
              if (layout.lanes.width < layout.token + 8) throw new Error(`lane ${layout.lanes.width} px is not wider than the ${layout.token} px token plus 8 at ${where}`)
              const blocked = laneViolations(layout)
              if (blocked.length > 0) throw new Error(`${blocked.length} boxes block a lane at ${where}: ${JSON.stringify(blocked[0])}`)
              checked += 1
            }
          }
        }
      }
    }
    expect(checked).toBe(WIDTHS.length * 31 * 11 * READ_DOORS.length * WRITE_DOORS.length)
  })

  it('keeps every shown seat in place as agents and steps are appended', () => {
    for (const width of [358, 640, 960, 1440]) {
      for (let n = 0; n < 30; n += 1) {
        const before = layoutRoom(plan(n, 2, 1, 1), width)
        const after = layoutRoom(plan(n + 1, 2, 1, 1), width)
        for (const [key, seat] of before.seats) {
          const later = after.seats.get(key)
          if (later) expect(later.box, `${key} moved at width ${width} when agent ${n} arrived`).toEqual(seat.box)
        }
      }
      for (let n = 0; n < 10; n += 1) {
        const before = layoutRoom(plan(2, n, 1, 1), width)
        const after = layoutRoom(plan(2, n + 1, 1, 1), width)
        for (const [key, seat] of before.seats) {
          const later = after.seats.get(key)
          if (later) expect(later.box, `${key} moved at width ${width} when step ${n} arrived`).toEqual(seat.box)
        }
      }
    }
  })

  it('names everyone it hides in an overflow seat, in slot order, and points them at it', () => {
    const layout = layoutRoom(plan(30, 10, 1, 1), 640)
    const shownAgents = [...layout.seats.keys()].filter((key) => key.startsWith('agent:'))
    const overflowAgents = layout.overflow.find((seat) => seat.row === 'agents')
    const overflowPeople = layout.overflow.find((seat) => seat.row === 'people')
    expect(overflowAgents).toBeDefined()
    expect(overflowPeople).toBeDefined()
    expect(shownAgents.length + (overflowAgents?.hidden.length ?? 0)).toBe(30)
    expect(overflowAgents?.hidden).toEqual([...(overflowAgents?.hidden ?? [])].sort((a, b) => slotOf(a) - slotOf(b)))
    const hiddenAgent = overflowAgents?.hidden[0]
    if (!hiddenAgent) throw new Error('nothing hidden')
    const point = layout.point({ at: 'agent', id: agentId(hiddenAgent.slice('agent:'.length)) })
    const seat = overflowAgents?.seat.avatar
    expect(seat && point.x >= seat.x && point.x <= seat.x + seat.w && point.y >= seat.y && point.y <= seat.y + seat.h).toBe(true)
    const hiddenStep = overflowPeople?.hidden.at(-1)
    expect(hiddenStep).toBe(stepSeatKey(9))
  })

  it('places a speech slot inside the room above every shown agent, with the tail over its avatar', () => {
    for (const width of [640, 960, 1440]) {
      const layout = layoutRoom(plan(5, 1, 1, 1), width)
      expect(layout.speechBand).not.toBeNull()
      for (const [key, seat] of layout.seats) {
        const slot = layout.speech.get(key)
        if (!key.startsWith('agent:')) {
          expect(slot).toBeUndefined()
          continue
        }
        expect(slot, `${key} has no speech slot at ${width}`).toBeDefined()
        if (!slot || !layout.speechBand) continue
        expect(inside(slot.card, layout.speechBand)).toBe(true)
        expect(slot.tailX).toBeGreaterThanOrEqual(seat.avatar.x)
        expect(slot.tailX).toBeLessThanOrEqual(seat.avatar.x + seat.avatar.w)
      }
    }
    expect(layoutRoom(plan(5, 1, 1, 1), 390).speechBand).toBeNull()
    expect(layoutRoom(plan(5, 1, 1, 1), 390).speech.size).toBe(0)
  })

  it('routes every hand-off through the lanes without crossing a label', () => {
    for (const width of [358, 640, 960, 1440]) {
      for (const [agents, steps, read, write] of [
        [1, 1, 1, 1],
        [3, 2, 2, 1],
        [7, 3, 3, 3],
        [12, 10, 6, 6],
      ] as const) {
        const layout = layoutRoom(plan(agents, steps, read, write), width)
        for (const route of everyRoute(layout)) {
          const crossed = routeCrossings(layout, route.from, route.to)
          expect(crossed, `${nameOf(route.from)} to ${nameOf(route.to)} crosses ${crossed.map((b) => b.who.role).join(', ')} at ${width} with ${agents}/${steps}/${read}/${write}`).toEqual([])
        }
      }
    }
  })

  it('seeds a write door the proposal has not named yet and keeps its place once named', () => {
    const seeded = layoutRoom(plan(2, 1, 1, 1, 1), 960)
    const seededDoor = seeded.doors.find((door) => door.side === 'write')
    expect(seededDoor?.key).toBeNull()
    expect(seededDoor?.label).toBe('Write 0')
    expect(seededDoor?.checker).not.toBeNull()
    const named = layoutRoom(plan(2, 1, 1, 1, 0), 960)
    expect(named.doors.find((door) => door.side === 'write')?.box).toEqual(seededDoor?.box)
  })

  it('answers the design metrics: 72 px avatars from 640 and 40 px below, with 12 px floors kept by the component', () => {
    expect(layoutRoom(plan(1, 0, 0, 0), 640).seats.get('agent:a0')?.avatar.w).toBe(72)
    expect(layoutRoom(plan(1, 0, 0, 0), 639).seats.get('agent:a0')?.avatar.w).toBe(40)
    expect(layoutRoom(plan(1, 0, 0, 0), 639).size).toBe('compact')
    expect(layoutRoom(plan(1, 0, 0, 0), 640).size).toBe('wide')
  })

  it("makes the demo's stage 588 px tall at every wide width", () => {
    for (const width of [640, 960, 1100, 1440]) expect(layoutRoom(plan(2, 1, 1, 1, 1), width).height, `at ${width}`).toBe(588)
  })

  it('frames the ticket with a table at most 432 px wide that still holds the ticket spot and its rejected edge', () => {
    for (const width of [640, 760, 960, 1100, 1440]) {
      const layout = layoutRoom(plan(2, 1, 1, 1, 1), width)
      expect(layout.table.w, `at ${width}`).toBeLessThanOrEqual(432)
      expect(inside(layout.ticketSpot, layout.table), `ticket spot at ${width}`).toBe(true)
      expect(inside(layout.tableEdge, layout.table), `table edge at ${width}`).toBe(true)
      expect(layout.tableEdge.w).toBe(layout.ticketSpot.w)
      expect(layout.tableEdge.x).toBeGreaterThanOrEqual(layout.ticketSpot.x)
    }
    expect(layoutRoom(plan(2, 1, 1, 1, 1), 1440).table.w).toBe(432)
  })

  it("puts the Teams door's label in the bottom 40 px of its box, left of the opening", () => {
    const layout = layoutRoom(plan(2, 1, 1, 1, 1), 1440)
    const teams = layout.doors.find((door) => door.side === 'teams')
    if (!teams) throw new Error('no Teams door')
    expect(teams.labelBox.h).toBe(40)
    expect(teams.labelBox.y + teams.labelBox.h).toBe(teams.box.y + teams.box.h)
    expect(teams.labelBox.x + teams.labelBox.w).toBeLessThanOrEqual(teams.opening.x)
  })

  it('reserves two name lines and two status lines under a compact avatar, so a label wraps instead of truncating', () => {
    const m = ROOM_METRICS.compact
    expect(m.nameLines).toBe(2)
    expect(m.statusLines).toBe(2)
    const seat = layoutRoom(plan(3, 1, 1, 1), 390).seats.get('agent:a1')
    if (!seat) throw new Error('no seat')
    expect(seat.box.h - seat.avatar.h).toBeGreaterThanOrEqual(m.nameLines * m.nameLine + m.statusLines * m.statusLine + 2 * m.labelGap)
    expect(seat.box.w - 2 * m.labelInset).toBeGreaterThanOrEqual(80)
  })

  it('walks straight between two adjacent seats in one row, at avatar height', () => {
    for (const width of [390, 640, 1440]) {
      const layout = layoutRoom(plan(3, 2, 1, 1), width)
      const host = layout.point({ at: 'agent', id: agentId('a0') })
      const left = layout.point({ at: 'agent', id: agentId('a1') })
      const route = layout.route({ at: 'agent', id: agentId('a0') }, { at: 'agent', id: agentId('a1') })
      expect(route, `at ${width}`).toEqual([host, left])
      expect(layout.route({ at: 'agent', id: agentId('a2') }, { at: 'agent', id: agentId('a0') })).toEqual([layout.point({ at: 'agent', id: agentId('a2') }), host])
    }
  })

  it('goes round through the lane when another seat sits between, and still crosses no label', () => {
    const layout = layoutRoom(plan(4, 1, 1, 1), 1440)
    const route = layout.route({ at: 'agent', id: agentId('a0') }, { at: 'agent', id: agentId('a3') })
    expect(route.length).toBeGreaterThan(2)
    expect(route.some((p) => p.y === layout.lanes.top)).toBe(true)
    expect(routeCrossings(layout, { at: 'agent', id: agentId('a0') }, { at: 'agent', id: agentId('a3') })).toEqual([])
  })

  it('leaves a seat through its outer gutter when the inner one has a neighbour', () => {
    const layout = layoutRoom(plan(3, 1, 1, 1), 390)
    const a1 = layout.seats.get('agent:a1')
    if (!a1) throw new Error('no seat')
    const route = layout.route({ at: 'agent', id: agentId('a1') }, { at: 'door', key: doorKey('write_0') })
    const gutterX = route[1]?.x ?? Number.NaN
    expect(gutterX).toBeLessThan(a1.box.x)
  })

  it('starts and ends table routes at the ticket card edge, never at its centre', () => {
    for (const width of [390, 960]) {
      const layout = layoutRoom(plan(2, 1, 1, 1), width)
      const spot = layout.ticketSpot
      const toTeams = layout.route({ at: 'table' }, { at: 'teams' })
      expect(toTeams[0]).toEqual({ x: spot.x + spot.w / 2, y: spot.y + spot.h })
      const toJira = layout.route({ at: 'table' }, { at: 'door', key: doorKey('write_0') })
      expect(toJira[0]).toEqual({ x: spot.x + spot.w, y: spot.y + spot.h / 2 })
      const fromHost = layout.route({ at: 'agent', id: agentId('a0') }, { at: 'table' })
      expect(fromHost.at(-1)).toEqual({ x: spot.x + spot.w / 2, y: spot.y })
      expect(layout.point({ at: 'table' })).toEqual({ x: spot.x + spot.w / 2, y: spot.y + spot.h / 2 })
    }
  })

  it('lets a seat tile walk as itself only straight into a neighbouring seat, or up through the Teams door to the last seat', () => {
    const host: Anchor = { at: 'agent', id: agentId('a0') }
    const teams: Anchor = { at: 'teams' }
    for (const width of [640, 960, 1100, 1440]) {
      for (const [agents, steps] of [
        [2, 1],
        [3, 2],
        [4, 1],
      ] as const) {
        const layout = layoutRoom(plan(agents, steps, 1, 1), width)
        const where = `at ${width} with ${agents} agents and ${steps} steps`
        for (const slot of [1, 2]) {
          if (slot >= agents) continue
          const guest: Anchor = { at: 'agent', id: agentId(`a${slot}`) }
          expect(layout.walk(host, guest), `host to slot ${slot} ${where}`).toEqual([layout.point(host), layout.point(guest)])
        }
        if (agents === 4 && layout.seats.has('agent:a3')) {
          expect(layout.walk(host, { at: 'agent', id: agentId('a3') }), `host to a seat two away ${where}`).toBeNull()
        }
        const last: Anchor = { at: 'step', index: steps - 1 }
        const teamsDoor = layout.doors.find((door) => door.side === 'teams')
        if (!teamsDoor) throw new Error('no Teams door')
        const { x: cx, y: cy } = layout.point(last)
        expect(layout.walk(teams, last), `Teams to the last seat ${where}`).toEqual([teamsDoor.outside, { x: teamsDoor.approach.x, y: cy }, { x: cx, y: cy }])
        if (layout.seats.has('starter') && layout.seats.has(stepSeatKey(steps - 1))) {
          expect(layout.walk(teams, { at: 'starter' }), `Teams to a seat with another to its right ${where}`).toBeNull()
        }
      }
    }
  })

  it('never lets a walking tile touch a label or the Safety checker', () => {
    const avatar = { wide: ROOM_METRICS.wide.avatar, compact: ROOM_METRICS.compact.avatar }
    let walks = 0
    for (const width of [390, 640, 960, 1100, 1440]) {
      for (const [agents, steps] of [
        [2, 1],
        [3, 2],
        [4, 1],
        [6, 3],
      ] as const) {
        const layout = layoutRoom(plan(agents, steps, 1, 1), width)
        const host: Anchor = { at: 'agent', id: agentId('a0') }
        const pairs: { from: Anchor; to: Anchor }[] = []
        for (let slot = 1; slot < agents; slot += 1) pairs.push({ from: host, to: { at: 'agent', id: agentId(`a${slot}`) } })
        pairs.push({ from: { at: 'teams' }, to: { at: 'starter' } })
        for (let index = 0; index < steps; index += 1) pairs.push({ from: { at: 'teams' }, to: { at: 'step', index } })
        for (const { from, to } of pairs) {
          const path = layout.walk(from, to)
          if (!path) continue
          walks += 1
          const own = seatKeyOf(to)
          const obstacles: Box[] = []
          for (const [key, seat] of layout.seats) if (key !== own) obstacles.push(seat.label)
          for (const seat of layout.overflow) if (!seat.hidden.includes(own as SeatKey)) obstacles.push(seat.seat.label)
          for (const door of layout.doors) {
            obstacles.push(door.labelBox)
            if (door.checker) obstacles.push(door.checker)
          }
          for (let i = 1; i < path.length; i += 1) {
            const a = path[i - 1] as Point
            const b = path[i] as Point
            const touched = obstacles.filter((box) => segmentCrosses(a, b, box, avatar[layout.size] / 2))
            expect(touched, `${nameOf(from)} to ${nameOf(to)} at ${width} with ${agents}/${steps}, segment ${i}`).toEqual([])
          }
        }
      }
    }
    expect(walks).toBeGreaterThan(20)
  })

  it('lets a token through a write door under the Safety checker, with room to spare', () => {
    for (const width of [390, 640, 1440]) {
      const layout = layoutRoom(plan(2, 1, 1, 1), width)
      const door = layout.doors.find((candidate) => candidate.side === 'write')
      if (!door?.checker) throw new Error('no write door')
      expect(door.checker.y).toBe(door.opening.y)
      expect(door.approach.y - layout.token / 2, `at ${width}`).toBeGreaterThanOrEqual(door.checker.y + door.checker.h + 4)
      expect(door.approach.y + layout.token / 2).toBeLessThanOrEqual(door.opening.y + door.opening.h)
    }
  })
})

function slotOf(key: SeatKey): number {
  return Number(key.slice('agent:a'.length))
}

function nameOf(a: Anchor): string {
  switch (a.at) {
    case 'agent':
      return `agent ${a.id}`
    case 'step':
      return `step ${a.index}`
    case 'door':
      return `door ${a.key}`
    default:
      return a.at
  }
}

function everyRoute(layout: RoomLayout): { from: Anchor; to: Anchor }[] {
  const seats: Anchor[] = []
  for (const key of layout.seats.keys()) {
    if (key === 'starter') seats.push({ at: 'starter' })
    else if (key.startsWith('step:')) seats.push({ at: 'step', index: Number(key.slice('step:'.length)) })
    else seats.push({ at: 'agent', id: agentId(key.slice('agent:'.length)) })
  }
  const agents = seats.filter((a) => a.at === 'agent')
  const people = seats.filter((a) => a.at !== 'agent')
  const doors: Anchor[] = layout.doors.flatMap((door) => (door.key && door.key !== 'teams' ? [{ at: 'door', key: door.key }] : []))
  const routes: { from: Anchor; to: Anchor }[] = []
  for (const agent of agents) {
    for (const door of doors) routes.push({ from: agent, to: door }, { from: door, to: agent })
    routes.push({ from: agent, to: { at: 'table' } })
    const host = agents[0]
    if (host && host !== agent) routes.push({ from: host, to: agent }, { from: agent, to: host })
  }
  for (const door of doors) routes.push({ from: { at: 'table' }, to: door }, { from: door, to: { at: 'table' } })
  routes.push({ from: { at: 'table' }, to: { at: 'teams' } }, { from: { at: 'table' }, to: { at: 'table_edge' } })
  for (const person of people) routes.push({ from: { at: 'teams' }, to: person }, { from: person, to: { at: 'table' } })
  return routes
}
