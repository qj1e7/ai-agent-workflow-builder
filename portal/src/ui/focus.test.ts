import { afterEach, describe, expect, it, vi } from 'vitest'
import { focusIfFocusFell, placeAfterRedraw } from './focus'

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

describe('a notice that takes focus only when focus fell to the page', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function page(focused: 'body' | 'nothing' | 'a box') {
    const body = { name: 'body' }
    const notice = { focus: vi.fn() }
    const box = { name: 'a box' }
    const activeElement = focused === 'body' ? body : focused === 'a box' ? box : null
    vi.stubGlobal('document', { body, activeElement, getElementById: (id: string) => (id === 'people-left' ? notice : null) })
    return notice
  }

  it('takes it when the focused row left and focus fell to the page body', () => {
    const notice = page('body')
    focusIfFocusFell('people-left')
    expect(notice.focus).toHaveBeenCalledOnce()
  })

  it('takes it when nothing has focus', () => {
    const notice = page('nothing')
    focusIfFocusFell('people-left')
    expect(notice.focus).toHaveBeenCalledOnce()
  })

  it('leaves focus where it is when it is still on another control', () => {
    const notice = page('a box')
    focusIfFocusFell('people-left')
    expect(notice.focus).not.toHaveBeenCalled()
  })
})
