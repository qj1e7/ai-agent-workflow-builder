import { describe, expect, it } from 'vitest'
import { breakPoint, clampLeft, fillScale, orientationOf, parcelPoint, railBox, type Point } from './geometry'

/** The release check's six nodes at 1440 (a 203 px column from x 213) and at 390 (stacked from y 240). */
const ROW: Point[] = [213, 416, 619, 822, 1025, 1228].map((x) => ({ x, y: 437 }))
const COLUMN: Point[] = [240, 356, 432, 508, 585, 661].map((y) => ({ x: 42, y }))

describe('the line geometry', () => {
  it('reads the orientation from where the nodes landed', () => {
    expect(orientationOf(ROW)).toBe('horizontal')
    expect(orientationOf(COLUMN)).toBe('vertical')
  })

  it('puts the parcel on its node, or in front of the barrier', () => {
    expect(parcelPoint(ROW, 'horizontal', 1, false)).toEqual({ x: 416, y: 437 })
    expect(parcelPoint(ROW, 'horizontal', 3, true)).toEqual({ x: 720, y: 437 })
    expect(parcelPoint(COLUMN, 'vertical', 3, true)).toEqual({ x: 42, y: 462 })
    expect(parcelPoint(ROW, 'horizontal', 9, false)).toBeNull()
  })

  it('runs the rail from the first node to the last', () => {
    expect(railBox(ROW, 'horizontal')).toEqual({ left: 213, top: 433, width: 1015, height: 8 })
    expect(railBox(COLUMN, 'vertical')).toEqual({ left: 39, top: 240, width: 6, height: 421 })
  })

  it('fills the line up to the parcel, clamped to the rail', () => {
    expect(fillScale(ROW, 'horizontal', ROW[0] ?? null)).toBe(0)
    expect(fillScale(ROW, 'horizontal', { x: 720.5, y: 437 })).toBeCloseTo(0.5)
    expect(fillScale(ROW, 'horizontal', ROW[5] ?? null)).toBe(1)
    expect(fillScale(ROW, 'horizontal', { x: 0, y: 437 })).toBe(0)
    expect(fillScale(ROW, 'horizontal', null)).toBe(0)
  })

  it('snaps the break just past the failed node and short of the next one', () => {
    expect(breakPoint(ROW, 'horizontal', 1)).toEqual({ x: 528, y: 437 })
    expect(breakPoint(COLUMN, 'vertical', 1)).toEqual({ x: 42, y: 400 })
    const tight = [0, 100, 200].map((x) => ({ x, y: 0 }))
    expect(breakPoint(tight, 'horizontal', 0)).toEqual({ x: 70, y: 0 })
  })

  it('centres a panel on its stop and keeps it inside the route', () => {
    expect(clampLeft(822, 400, 0, 1216)).toBe(622)
    expect(clampLeft(101, 400, 0, 1216)).toBe(0)
    expect(clampLeft(1115, 400, 0, 1216)).toBe(816)
  })
})
