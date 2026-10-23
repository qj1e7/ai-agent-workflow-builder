export interface LayoutReport {
  overflow: number
  undersizedTargets: { target: string; text: string; width: number; height: number }[]
  smallText: { text: string; size: number; parent: string }[]
}

export const MIN_TARGET = 44
export const MIN_TEXT = 12

// Runs inside the page, so it cannot use anything imported at module level.
export function measureLayout({ minTarget, minText }: { minTarget: number; minText: number }): LayoutReport {
  const describe = (el: Element): string => {
    const id = el.id ? `#${el.id}` : ''
    const cls = typeof el.className === 'string' && el.className ? `.${el.className.split(/\s+/)[0]}` : ''
    return `${el.tagName.toLowerCase()}${id}${cls}`
  }
  const rendered = (el: Element): boolean => {
    if (el.closest('.visually-hidden')) return false
    for (let node: Element | null = el; node; node = node.parentElement) {
      const style = getComputedStyle(node)
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false
      if (Number(style.opacity) === 0) return false
    }
    const rect = el.getBoundingClientRect()
    return rect.width > 0 && rect.height > 0
  }

  const targetSelector = [
    'button',
    'a[href]',
    'input:not([type=hidden])',
    'select',
    'textarea',
    'summary',
    '[role=slider]',
    '[role=switch]',
    '[role=menuitemradio]',
    '[role=tab]',
  ].join(',')

  const undersizedTargets = [...document.querySelectorAll(targetSelector)]
    .filter(rendered)
    .map((el) => ({ el, rect: el.getBoundingClientRect() }))
    .filter(({ rect }) => rect.width < minTarget - 0.5 || rect.height < minTarget - 0.5)
    .map(({ el, rect }) => ({
      target: describe(el),
      text: (el.getAttribute('aria-label') ?? el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 60),
      width: Math.round(rect.width * 10) / 10,
      height: Math.round(rect.height * 10) / 10,
    }))

  const smallText: LayoutReport['smallText'] = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.textContent ?? '').trim()
    const parent = node.parentElement
    if (!text || !parent || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName) || !rendered(parent)) continue
    let size = parseFloat(getComputedStyle(parent).fontSize)
    if (parent instanceof SVGGraphicsElement) size *= parent.getScreenCTM()?.a ?? 1
    if (size < minText - 0.01) smallText.push({ text: text.slice(0, 50), size: Math.round(size * 100) / 100, parent: describe(parent) })
  }

  return {
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    undersizedTargets,
    smallText,
  }
}
