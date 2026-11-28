import { describe, expect, it } from 'vitest'
import { SLIM_LIST_FROM, besideChat } from './chatLayout'

describe('what sits beside the chat', () => {
  it('docks the slim list in a wide window and drops the pinned line, so the glance is said once', () => {
    expect(besideChat(true, false)).toEqual({ slim: true, pinned: false })
  })

  it('gives the slim list’s place to the side panel, and the pinned line comes back with it', () => {
    expect(besideChat(true, true)).toEqual({ slim: false, pinned: true })
  })

  it('has the pinned line and no slim list in a narrow window, panel or not', () => {
    expect(besideChat(false, false)).toEqual({ slim: false, pinned: true })
    expect(besideChat(false, true)).toEqual({ slim: false, pinned: true })
  })

  it('goes narrow under 1080 px, as the sketch does', () => {
    expect(SLIM_LIST_FROM).toBe('(min-width: 1080px)')
  })
})
