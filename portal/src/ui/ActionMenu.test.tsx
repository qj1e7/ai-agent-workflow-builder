import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { IconTrash } from './icons'
import { ActionMenu, focusAfter, MenuItems, type MenuItem } from './ActionMenu'

const ITEMS: MenuItem[] = [
  { key: 'run', label: 'Run now', onSelect: () => undefined },
  { key: 'schedule', label: 'Change schedule', onSelect: () => undefined },
  { key: 'delete', label: 'Delete', icon: IconTrash, danger: true, onSelect: () => undefined },
]

describe('moving through the menu with the arrow keys', () => {
  it('goes down and up, and wraps at both ends', () => {
    expect(focusAfter('ArrowDown', 0, 3)).toBe(1)
    expect(focusAfter('ArrowDown', 2, 3)).toBe(0)
    expect(focusAfter('ArrowUp', 1, 3)).toBe(0)
    expect(focusAfter('ArrowUp', 0, 3)).toBe(2)
  })

  it('jumps to the first and last item with Home and End', () => {
    expect(focusAfter('Home', 2, 3)).toBe(0)
    expect(focusAfter('End', 0, 3)).toBe(2)
  })
})

describe('the menu', () => {
  it('starts closed, with its button saying it opens a menu', () => {
    const html = renderToStaticMarkup(<ActionMenu items={ITEMS} buttonRef={{ current: null }} />)
    expect(html).toMatch(/<button[^>]*aria-haspopup="menu"[^>]*aria-expanded="false"/)
    expect(html).not.toContain('role="menu"')
  })

  it('opens as a menu named More actions, with each item a menuitem', () => {
    const html = renderToStaticMarkup(<MenuItems id="m" label="More actions" items={ITEMS} onPick={() => undefined} />)
    expect(html).toMatch(/role="menu"[^>]*aria-label="More actions"/)
    expect([...html.matchAll(/role="menuitem"[^>]*>(?:<svg[\s\S]*?<\/svg>)?([^<]*)</g)].map((m) => m[1])).toEqual(['Run now', 'Change schedule', 'Delete'])
  })

  it('puts a divider before the danger item and none before the others', () => {
    const html = renderToStaticMarkup(<MenuItems id="m" label="More actions" items={ITEMS} onPick={() => undefined} />)
    expect(html.match(/<hr/g)).toHaveLength(1)
    expect(html.indexOf('<hr')).toBeLessThan(html.indexOf('>Delete<'))
    expect(html.indexOf('<hr')).toBeGreaterThan(html.indexOf('>Change schedule<'))
  })

  it('draws no divider when the danger item is the only one', () => {
    const html = renderToStaticMarkup(<MenuItems id="m" label="More actions" items={ITEMS.slice(2)} onPick={() => undefined} />)
    expect(html).not.toContain('<hr')
  })
})
