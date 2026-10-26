import { describe, expect, it } from 'vitest'
import { sideFor } from './watch'

const SCREEN = { width: 1280, height: 860 }

describe('where the card sits', () => {
  it('stays bottom right when nothing it must leave clear is there', () => {
    expect(sideFor([], SCREEN)).toBe('right')
    expect(sideFor([null], SCREEN)).toBe('right')
    expect(sideFor([{ top: 10, left: 1100, width: 120, height: 40 }], SCREEN)).toBe('right')
    expect(sideFor([{ top: 600, left: 100, width: 200, height: 40 }], SCREEN)).toBe('right')
  })

  it('moves left when the stop is under it', () => {
    expect(sideFor([{ top: 600, left: 1080, width: 140, height: 44 }], SCREEN)).toBe('left')
  })

  it('moves left for a message the step asks the person to watch, even when the stop is elsewhere', () => {
    const button = { top: 220, left: 627, width: 110, height: 44 }
    const message = { top: 370, left: 627, width: 595, height: 24 }
    expect(sideFor([button, message], SCREEN)).toBe('left')
  })

  it('stays right when the stop spans the whole width, since the left is no better', () => {
    expect(sideFor([{ top: 245, left: 28, width: 1224, height: 700 }], SCREEN)).toBe('right')
  })
})
