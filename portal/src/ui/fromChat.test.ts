import { describe, expect, it } from 'vitest'
import { FROM_CHAT, openedFromChat } from './fromChat'
import { FROM_LIST } from './fromList'

describe('a page the chat opened', () => {
  it('is known by the state the link passed', () => {
    expect(openedFromChat(FROM_CHAT)).toBe(true)
    expect(openedFromChat(FROM_LIST)).toBe(false)
    expect(openedFromChat(null)).toBe(false)
    expect(openedFromChat(undefined)).toBe(false)
    expect(openedFromChat('fromChat')).toBe(false)
  })
})
