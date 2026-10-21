import type { Locator, Page } from '@playwright/test'

export interface Ring {
  style: string
  width: number
}

export interface Stop {
  id: number
  label: string
  top: number
  bottom: number
  left: number
  rest: Ring
  focused: Ring
  /** Set only when the styles show no ring (the range input draws it on its thumb), by comparing shots of the focused and unfocused element. */
  pixelsChange: boolean | null
}

export interface Walk {
  stops: Stop[]
  unreached: string[]
}

const MAX_TABS = 120

// Stamps every tabbable element with an id, its name and its unfocused ring, so the focused ring can be compared with it later.
async function stampTabbables(page: Page): Promise<number> {
  return page.evaluate(() => {
    const name = (el: HTMLElement) => {
      const words = el.getAttribute('aria-label') ?? (el instanceof HTMLInputElement ? el.labels?.[0]?.textContent : null) ?? el.textContent ?? ''
      return words.trim().replace(/\s+/g, ' ').slice(0, 50) || el.tagName
    }
    // Tab enters a radio group once: on the checked radio, or on the first when none is checked.
    const tabStopOfGroup = (el: HTMLElement) => {
      if (!(el instanceof HTMLInputElement) || el.type !== 'radio' || el.name === '') return true
      const group = [...document.querySelectorAll<HTMLInputElement>('input[type=radio]')].filter((radio) => radio.name === el.name)
      return el === (group.find((radio) => radio.checked) ?? group[0])
    }
    const ring = (el: Element) => {
      const style = getComputedStyle(el, el instanceof HTMLInputElement && el.type === 'range' ? '::-webkit-slider-thumb' : null)
      const outline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0 ? `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor} +${style.outlineOffset}` : 'none'
      return `${outline} | ${style.boxShadow}`
    }
    const rendered = (el: Element) => {
      if (el.closest('.visually-hidden')) return false
      for (let node: Element | null = el; node; node = node.parentElement) {
        const style = getComputedStyle(node)
        if (style.display === 'none' || style.visibility === 'hidden') return false
      }
      const rect = el.getBoundingClientRect()
      return rect.width > 0 && rect.height > 0
    }
    const selector = 'a[href], button:not([disabled]), input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
    const found = [...document.querySelectorAll<HTMLElement>(selector)].filter((el) => rendered(el) && tabStopOfGroup(el))
    found.forEach((el, index) => {
      el.dataset['e2eStop'] = String(index)
      el.dataset['e2eName'] = name(el)
      el.dataset['e2eRest'] = ring(el)
    })
    return found.length
  })
}

// Runs inside the page after each Tab.
function describeFocus(): Omit<Stop, 'id' | 'pixelsChange'> & { id: number | null; atBody: boolean } {
  const el = document.activeElement as HTMLElement | null
  if (!el || el === document.body || el === document.documentElement) return { id: null, atBody: true, label: '', top: 0, bottom: 0, left: 0, rest: { style: '', width: 0 }, focused: { style: '', width: 0 } }
  const style = getComputedStyle(el, el instanceof HTMLInputElement && el.type === 'range' ? '::-webkit-slider-thumb' : null)
  const outlineWidth = style.outlineStyle !== 'none' ? parseFloat(style.outlineWidth) : 0
  const outline = outlineWidth > 0 ? `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor} +${style.outlineOffset}` : 'none'
  const rect = el.getBoundingClientRect()
  let fixed = false
  for (let node: Element | null = el; node; node = node.parentElement) {
    const position = getComputedStyle(node).position
    if (position === 'fixed' || position === 'sticky') fixed = true
  }
  const docHeight = document.documentElement.scrollHeight
  const pinnedToBottom = fixed && rect.top > window.innerHeight / 2
  const top = pinnedToBottom ? docHeight - rect.height : fixed ? rect.top : rect.top + window.scrollY
  const shadow = style.boxShadow
  return {
    id: el.dataset['e2eStop'] === undefined ? -1 : Number(el.dataset['e2eStop']),
    atBody: false,
    label: el.dataset['e2eName'] ?? el.tagName,
    top,
    bottom: top + rect.height,
    left: rect.left + window.scrollX,
    rest: { style: el.dataset['e2eRest'] ?? '', width: 0 },
    focused: { style: `${outline} | ${shadow}`, width: Math.max(outlineWidth, shadow !== 'none' ? 1 : 0) },
  }
}

async function pixelsChange(page: Page): Promise<boolean> {
  const box = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement
    ;(window as unknown as { e2eFocused: HTMLElement }).e2eFocused = el
    const rect = el.getBoundingClientRect()
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  })
  const pad = 8
  const viewport = page.viewportSize() ?? { width: 1440, height: 900 }
  const x = Math.max(0, box.x - pad)
  const y = Math.max(0, box.y - pad)
  const clip = { x, y, width: Math.min(viewport.width - x, box.width + 2 * pad), height: Math.min(viewport.height - y, box.height + 2 * pad) }
  await page.waitForTimeout(250)
  const focused = await page.screenshot({ clip })
  await page.evaluate(() => (window as unknown as { e2eFocused: HTMLElement }).e2eFocused.blur())
  await page.waitForTimeout(250)
  const rest = await page.screenshot({ clip })
  await page.evaluate(() => (window as unknown as { e2eFocused: HTMLElement }).e2eFocused.focus())
  return !focused.equals(rest)
}

/** Presses Tab from the top of the page until focus comes round again, recording each stop. */
export async function walkTabs(page: Page): Promise<Walk> {
  const total = await stampTabbables(page)
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    document.body.tabIndex = -1
    document.body.focus()
    document.body.removeAttribute('tabindex')
    window.scrollTo(0, 0)
  })
  const stops: Stop[] = []
  const seen = new Set<number>()
  for (let press = 0; press < MAX_TABS; press += 1) {
    await page.keyboard.press('Tab')
    const at = await page.evaluate(describeFocus)
    if (at.atBody || at.id === null || seen.has(at.id)) break
    seen.add(at.id)
    const noRingInStyles = at.focused.width === 0 || at.focused.style === at.rest.style
    stops.push({ id: at.id, label: at.label, top: at.top, bottom: at.bottom, left: at.left, rest: at.rest, focused: at.focused, pixelsChange: noRingInStyles ? await pixelsChange(page) : null })
  }
  const labels = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>('[data-e2e-stop]')].map((el) => [el.dataset['e2eStop'] ?? '', el.dataset['e2eName'] ?? el.tagName] as const))
  const unreached = labels.filter(([id]) => !seen.has(Number(id)) && Number(id) < total).map(([, label]) => label)
  return { stops, unreached }
}

export function outOfVisualOrder(stops: readonly Stop[]): string[] {
  const problems: string[] = []
  for (let index = 1; index < stops.length; index += 1) {
    const before = stops[index - 1]
    const after = stops[index]
    if (!before || !after) continue
    const overlap = Math.min(before.bottom, after.bottom) - Math.max(before.top, after.top)
    const sameRow = overlap > Math.min(before.bottom - before.top, after.bottom - after.top) / 2
    const inOrder = sameRow ? after.left >= before.left - 1 : after.top >= before.top - 1
    if (!inOrder) problems.push(`"${before.label}" (top ${Math.round(before.top)}, left ${Math.round(before.left)}) then "${after.label}" (top ${Math.round(after.top)}, left ${Math.round(after.left)})`)
  }
  return problems
}

export function withoutVisibleFocus(stops: readonly Stop[]): string[] {
  return stops.filter((stop) => (stop.focused.width === 0 || stop.focused.style === stop.rest.style) && stop.pixelsChange !== true).map((stop) => `"${stop.label}" focused: ${stop.focused.style}, at rest: ${stop.rest.style}`)
}

/** Presses Tab until the target has focus, so a control is reached the way a keyboard user reaches it. */
export async function tabTo(page: Page, target: Locator, limit = MAX_TABS): Promise<void> {
  for (let press = 0; press < limit; press += 1) {
    await page.keyboard.press('Tab')
    if (await target.evaluate((el) => el === document.activeElement)) return
  }
  throw new Error(`Tab never reached the target in ${limit} presses (see the call site in the stack)`)
}
