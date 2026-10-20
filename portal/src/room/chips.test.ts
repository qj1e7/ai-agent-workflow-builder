import { describe, expect, it } from 'vitest'
import { layoutOf, type RoomState } from '../run'
import { chipsFit } from './chips'
import { slideToward } from './motion'

const found: RoomState = {
  cursor: 9,
  startedAt: null,
  attempt: 1,
  phase: { name: 'working' },
  starter: null,
  agents: [],
  approval: null,
  doors: [{ side: 'teams' }],
  trips: [],
  finding: null,
  ticket: null,
  speech: null,
  caption: null,
  light: null,
}

describe('the finding chips', () => {
  it("fit the fixture's two release tags inside the ticket spot, under the From line, at wide and at compact", () => {
    const items = ['1.2.16', '1.2.15']
    const wide = layoutOf(found, 1440)
    const compact = layoutOf(found, 390)
    expect(wide.size).toBe('wide')
    expect(compact.size).toBe('compact')
    expect(chipsFit(items, wide.ticketSpot, 'wide', true)).toBe(true)
    expect(chipsFit(items, compact.ticketSpot, 'compact', true)).toBe(true)
  })

  it('fit six short chips at wide, and say so when six long ones cannot', () => {
    const wide = layoutOf(found, 1440).ticketSpot
    expect(chipsFit(['1', '2', '3', '4', '5', '6'], wide, 'wide', true)).toBe(true)
    expect(chipsFit(Array.from({ length: 6 }, () => 'x'.repeat(32)), wide, 'wide', true)).toBe(false)
  })

  it('start a chip part of the way towards its agent, never further than 48 px', () => {
    const near = slideToward({ x: 100, y: 100 }, { x: 140, y: 60 })
    expect(near.x).toBeCloseTo(14, 5)
    expect(near.y).toBeCloseTo(-14, 5)
    const far = slideToward({ x: 0, y: 0 }, { x: 300, y: 400 })
    expect(Math.hypot(far.x, far.y)).toBeCloseTo(48, 5)
    expect(far.x / far.y).toBeCloseTo(0.75, 5)
    expect(slideToward({ x: 5, y: 5 }, { x: 5, y: 5 })).toEqual({ x: 0, y: 0 })
  })
})
