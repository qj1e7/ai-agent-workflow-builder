import { describe, expect, it } from 'vitest'
import { nextTabStop, pressClosesCard } from './AgentCard'

interface Node {
  readonly name: string
  contains(other: Node | null): boolean
}

function node(name: string, children: readonly Node[] = []): Node {
  const self: Node = { name, contains: (other) => other === self || children.some((child) => child.contains(other)) }
  return self
}

const topClose = node('top Close')
const bottomClose = node('bottom Close')
const card = node('card', [topClose, node('How it works'), bottomClose])
const page = node('page')
const stops = [topClose, bottomClose]

describe('Tab in an open card', () => {
  it('goes to the first stop on Tab and the last on Shift+Tab when focus is on the card itself, as after a click on its text', () => {
    expect(nextTabStop(card, stops, card, false)).toBe(topClose)
    expect(nextTabStop(card, stops, card, true)).toBe(bottomClose)
  })

  it('comes back to the first stop on Tab and the last on Shift+Tab when focus is outside the card', () => {
    expect(nextTabStop(page, stops, card, false)).toBe(topClose)
    expect(nextTabStop(page, stops, card, true)).toBe(bottomClose)
    expect(nextTabStop(null, stops, card, true)).toBe(bottomClose)
  })

  it('wraps from the last stop to the first on Tab', () => {
    expect(nextTabStop(bottomClose, stops, card, false)).toBe(topClose)
  })

  it('wraps from the first stop to the last on Shift+Tab', () => {
    expect(nextTabStop(topClose, stops, card, true)).toBe(bottomClose)
  })

  it('leaves a move between two stops to the browser', () => {
    expect(nextTabStop(topClose, stops, card, false)).toBeNull()
    expect(nextTabStop(bottomClose, stops, card, true)).toBeNull()
  })
})

describe('a press on the dimmed page', () => {
  const edges = { left: 100, right: 500, top: 50, bottom: 650 }
  const onCard = { clientX: 300, clientY: 200 }
  const onPage = { clientX: 40, clientY: 200 }

  it('closes the card when it starts and ends on the dimmed page', () => {
    expect(pressClosesCard(onPage, onPage, edges)).toBe(true)
  })

  it('keeps the card open when a text selection on the card ends on the dimmed page', () => {
    expect(pressClosesCard(onCard, onPage, edges)).toBe(false)
  })

  it('keeps the card open when a press on the dimmed page ends on the card', () => {
    expect(pressClosesCard(onPage, onCard, edges)).toBe(false)
  })

  it('keeps the card open for a click with no press, as the keyboard sends', () => {
    expect(pressClosesCard(null, { clientX: 0, clientY: 0 }, edges)).toBe(false)
  })

  it('counts the card’s edge as on the card', () => {
    expect(pressClosesCard({ clientX: 100, clientY: 650 }, { clientX: 500, clientY: 50 }, edges)).toBe(false)
  })
})
