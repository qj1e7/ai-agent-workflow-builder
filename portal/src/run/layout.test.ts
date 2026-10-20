import { describe, expect, it } from 'vitest'
import { agentId, doorKey } from './brand'
import { collisions, layoutRoom, routeCrossings, type Box, type RoomLayout } from './layout'
import { agentSeatKey, stepSeatKey, type Anchor, type FloorPlan, type PlanDoor, type SeatKey } from './room'

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
  it('never collides, never leaves the floor, keeps the speech band and table clean', () => {
    let checked = 0
    for (const width of WIDTHS) {
      for (let agents = 0; agents <= 30; agents += 1) {
        for (let steps = 0; steps <= 10; steps += 1) {
          for (const read of READ_DOORS) {
            for (const write of WRITE_DOORS) {
              const layout = layoutRoom(plan(agents, steps, read, write), width)
              const bad = collisions(layout)
              if (bad.length > 0) {
                throw new Error(`${bad.length} collisions at width ${width}, ${agents} agents, ${steps} steps, ${read} read, ${write} write: ${JSON.stringify(bad[0])}`)
              }
              for (const box of layout.boxes) {
                if (!inside(box, layout.floor)) {
                  throw new Error(`${box.who.role} leaves the floor at width ${width}, ${agents} agents, ${steps} steps, ${read} read, ${write} write`)
                }
              }
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

  it('answers the design metrics: 56 px avatars from 640 and 40 px below, with 12 px floors kept by the component', () => {
    expect(layoutRoom(plan(1, 0, 0, 0), 640).seats.get('agent:a0')?.avatar.w).toBe(56)
    expect(layoutRoom(plan(1, 0, 0, 0), 639).seats.get('agent:a0')?.avatar.w).toBe(40)
    expect(layoutRoom(plan(1, 0, 0, 0), 639).size).toBe('compact')
    expect(layoutRoom(plan(1, 0, 0, 0), 640).size).toBe('wide')
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
