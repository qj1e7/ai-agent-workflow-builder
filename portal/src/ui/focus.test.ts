import { describe, expect, it } from 'vitest'
import { placeAfterRedraw } from './focus'

const ORDER = ['run', 'switch', 'delete'] as const

describe('where focus goes when a redraw removed the control a person pressed', () => {
  it('stays on that control when the redraw kept it', () => {
    expect(placeAfterRedraw(ORDER, 'run', ['run', 'switch', 'delete'])).toBe('run')
  })

  it('goes to the nearest control after it', () => {
    expect(placeAfterRedraw(ORDER, 'run', ['switch', 'delete'])).toBe('switch')
    expect(placeAfterRedraw(ORDER, 'run', ['delete'])).toBe('delete')
  })

  it('goes to the nearest control before it when none is left after it', () => {
    expect(placeAfterRedraw(ORDER, 'delete', ['run', 'switch'])).toBe('switch')
  })

  it('goes to the page heading when no control is left', () => {
    expect(placeAfterRedraw(ORDER, 'switch', [])).toBeNull()
  })
})
