import type { Page } from '@playwright/test'

/**
 * The fit check: every piece of text stays inside the card, box, button or pill that holds it, nothing is cut off, no two
 * pieces of text sit on top of each other, buttons side by side line up, and the page never scrolls sideways.
 *
 * `measure` is ported from the prototype's docs/design/ai-native-redesign/checks/fit.cjs and keeps its rules. Two changes:
 * it is typed, and it skips what carries data-fit-skip in place of the prototype's .testctl, because the Portal's class
 * names are hashed. Only SVG and decorative marks carry data-fit-skip. The Portal's floating Test controls are measured
 * like the rest of the page. `coverProblems` is new: it fails when a fixed or floating element covers a control.
 */

export interface Problem {
  readonly kind: 'cut off' | 'spills' | 'overlaps' | 'uneven' | 'covered' | 'sideways' | 'not settled'
  readonly where: string
  readonly text: string
}

/** Runs in the page, so it can use nothing from this file. Returns the problems found on what is drawn now. */
export function measure(): Problem[] {
  const SKIP = 'script, style, noscript, template, option, svg, [data-fit-skip]'
  const px = (v: string) => parseFloat(v) || 0
  const clear = (c: string) => !c || c === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(c)
  const name = (el: Element | null): string => {
    if (!el?.tagName) return '?'
    const cls = typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}` : ''
    return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${cls}`
  }
  const where = (el: Element): string => {
    const out: string[] = []
    for (let e: Element | null = el; e && e !== document.body && out.length < 4; e = e.parentElement) out.unshift(name(e))
    return out.join(' > ')
  }
  const hidden = (el: Element): boolean => {
    const shut = el.closest('details:not([open])')
    if (shut && !el.closest('summary')) return true
    for (let e: Element | null = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e)
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return true
      if ((cs.clip && cs.clip !== 'auto') || /inset\(50%/.test(cs.clipPath)) return true
      const r = e.getBoundingClientRect()
      if (r.width <= 1 && r.height <= 1 && cs.overflow !== 'visible') return true
    }
    return false
  }
  const bgOf = (el: Element): string => {
    for (let e: Element | null = el; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor
      if (!clear(c)) return c
    }
    return 'rgb(255, 255, 255)'
  }
  const isBox = (el: Element): boolean => {
    if (/^(BUTTON|INPUT|SELECT|TEXTAREA|DIALOG)$/.test(el.tagName)) return true
    const cs = getComputedStyle(el)
    if (cs.display === 'inline') return false
    const sides = (['Top', 'Right', 'Bottom', 'Left'] as const).filter((s) => px(cs[`border${s}Width`]) > 0 && cs[`border${s}Style`] !== 'none' && !clear(cs[`border${s}Color`])).length
    if (sides >= 3) return true
    return !clear(cs.backgroundColor) && el.parentElement !== null && cs.backgroundColor !== bgOf(el.parentElement)
  }
  const scrolls = (cs: CSSStyleDeclaration) => /auto|scroll/.test(cs.overflowX) || /auto|scroll/.test(cs.overflowY)
  /* A scrolling area or a layer fixed to the screen holds its text the way a card does. */
  const boxOf = (el: Element): Element | null => {
    for (let e: Element | null = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e)
      if (isBox(e) || scrolls(cs) || cs.position === 'fixed') return e
    }
    return null
  }
  const layerOf = (el: Element): Element => {
    for (let e: Element | null = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e)
      if (cs.position === 'fixed' || cs.position === 'sticky') return e
      if (cs.position === 'absolute' && cs.zIndex !== 'auto' && +cs.zIndex > 0) return e
      if (e.tagName === 'DIALOG' || /^(dialog|menu|tooltip|alertdialog)$/.test(e.getAttribute('role') ?? '')) return e
    }
    return document.body
  }
  interface Edges {
    left: number
    top: number
    right: number
    bottom: number
  }
  /* The part of a rect that shows through every clipping or scrolling ancestor. */
  const shown = (r: DOMRect, el: Element): Edges | null => {
    let { left, top, right, bottom } = r
    for (let e = el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e)
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue
      const b = e.getBoundingClientRect()
      if (cs.overflowX !== 'visible') {
        left = Math.max(left, b.left)
        right = Math.min(right, b.right)
      }
      if (cs.overflowY !== 'visible') {
        top = Math.max(top, b.top)
        bottom = Math.min(bottom, b.bottom)
      }
    }
    return right - left > 1 && bottom - top > 1 ? { left, top, right, bottom } : null
  }

  const problems: Problem[] = []
  interface Line extends Edges {
    h: number
    el: Element
    layer: Element
    snip: string
  }
  const lines: Line[] = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const seenClip = new Set<Element>()
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.textContent ?? '').replace(/\s+/g, ' ').trim()
    const el = n.parentElement
    if (!text || !el || el.closest(SKIP) || hidden(el)) continue
    const range = document.createRange()
    range.selectNodeContents(n)
    const rects = [...range.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5)
    if (!rects.length) continue
    const snip = text.length > 48 ? `${text.slice(0, 45)}...` : text

    /* Cut off: the text runs past an ancestor that hides overflow, or an ellipsis is showing. Text past a scrolling
       area is reached by scrolling, and nothing above a fixed layer clips it, so the walk stops at either. */
    for (let e: Element | null = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e)
      if (scrolls(cs)) break
      const hides = /hidden|clip/.test(cs.overflowX) || /hidden|clip/.test(cs.overflowY)
      if (hides) {
        const b = e.getBoundingClientRect()
        const out = rects.some((r) => r.left < b.left - 1 || r.right > b.right + 1 || (cs.overflowY !== 'visible' && r.bottom > b.bottom + 2) || (cs.overflowY !== 'visible' && r.top < b.top - 2))
        const ell = cs.textOverflow === 'ellipsis' && e.scrollWidth > e.clientWidth + 1
        const clamp = cs.webkitLineClamp && cs.webkitLineClamp !== 'none' && e.scrollHeight > e.clientHeight + 2
        if ((out || ell || clamp) && !seenClip.has(e)) {
          seenClip.add(e)
          problems.push({ kind: 'cut off', where: `${where(e)} (text in ${name(el)})`, text: snip })
        }
      }
      if (cs.position === 'fixed') break
    }

    /* Spills: the text sticks out of the nearest card, box, button or pill. Sideways it must stay inside the padding's
       inner edge; up and down, inside the border (a line box can be taller than its line-height). */
    const box = boxOf(el)
    if (box) {
      const b = box.getBoundingClientRect()
      const cs = getComputedStyle(box)
      const inL = b.left + px(cs.borderLeftWidth) + px(cs.paddingLeft) - 1
      const inR = b.right - px(cs.borderRightWidth) - px(cs.paddingRight) + 1
      const inT = b.top + px(cs.borderTopWidth) - 2
      const inB = b.bottom - px(cs.borderBottomWidth) + 2
      const tall = scrolls(cs)
      const bad = rects.find((r) => r.left < inL || r.right > inR || (!tall && (r.top < inT || r.bottom > inB)))
      if (bad) {
        const by = Math.round(Math.max(inL - bad.left, bad.right - inR, inT - bad.top, bad.bottom - inB))
        problems.push({ kind: 'spills', where: `${where(el)} (box ${name(box)})`, text: `${snip} [${String(by)}px]` })
      }
    }

    const layer = layerOf(el)
    rects.forEach((r) => {
      const s = shown(r, el)
      if (s) lines.push({ ...s, h: r.height, el, layer, snip })
    })
  }

  /* Overlaps: two pieces of text in the same layer drawn on top of each other. */
  lines.sort((a, b) => a.top - b.top)
  const seenPair = new Set<string>()
  for (let i = 0; i < lines.length; i += 1) {
    const a = lines[i]
    if (!a) continue
    for (let j = i + 1; j < lines.length; j += 1) {
      const b = lines[j]
      if (!b || b.top >= a.bottom) break
      if (a.el === b.el || a.layer !== b.layer || a.el.contains(b.el) || b.el.contains(a.el)) continue
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left)
      const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
      if (w > 2 && h > 0.5 * Math.min(a.h, b.h)) {
        const key = `${where(a.el)}|${where(b.el)}`
        if (seenPair.has(key)) continue
        seenPair.add(key)
        problems.push({ kind: 'overlaps', where: `${where(a.el)}  x  ${where(b.el)}`, text: `"${a.snip}" / "${b.snip}"` })
      }
    }
  }

  /* Uneven: buttons side by side in one row differ in height or sit off each other's centre. */
  const btnSel = 'button, a.btn, [role="button"], .btn'
  document.querySelectorAll('body *').forEach((parent) => {
    if (parent.closest(SKIP)) return
    const d = getComputedStyle(parent).display
    if (!/flex|grid/.test(d)) return
    const kids = [...parent.children].filter((k) => k.matches(btnSel) && !hidden(k)).map((k) => ({ k, r: k.getBoundingClientRect() })).filter((x) => x.r.height > 0)
    for (let i = 0; i < kids.length; i += 1) {
      for (let j = i + 1; j < kids.length; j += 1) {
        const first = kids[i]
        const second = kids[j]
        if (!first || !second) continue
        const a = first.r
        const b = second.r
        const sameRow = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5 * Math.min(a.height, b.height)
        if (!sameRow) continue
        /* A button drawn as a link has no box, so only its centre has to line up. */
        const boxed = (k: Element) => {
          const cs = getComputedStyle(k)
          return !clear(cs.backgroundColor) || (px(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none' && !clear(cs.borderTopColor))
        }
        const dh = boxed(first.k) && boxed(second.k) ? Math.abs(a.height - b.height) : 0
        const dc = Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2)
        if (dh > 2 || dc > 2) {
          problems.push({ kind: 'uneven', where: `${where(first.k)}  +  ${name(second.k)}`, text: `heights ${String(Math.round(a.height))}/${String(Math.round(b.height))}, centres ${String(Math.round(dc))}px apart` })
        }
      }
    }
  })

  const doc = document.documentElement
  if (doc.scrollWidth > doc.clientWidth + 1) problems.push({ kind: 'sideways', where: 'page', text: `${String(doc.scrollWidth)} > ${String(doc.clientWidth)}` })
  return problems
}

/**
 * Runs in the page. Adds a card with a word too long for it, a clipped label, two labels drawn on top of each other and two
 * unequal buttons. The Portal's content security policy refuses inline style attributes, so the styles are set through the
 * style object, which it allows.
 */
export function seedControl(): void {
  const put = <K extends keyof HTMLElementTagNameMap>(parent: HTMLElement, tag: K, text: string, style: Partial<CSSStyleDeclaration>): HTMLElementTagNameMap[K] => {
    const el = document.createElement(tag)
    el.textContent = text
    Object.assign(el.style, style)
    parent.append(el)
    return el
  }
  const host = document.createElement('div')
  put(host, 'div', 'Supercalifragilisticexpialidocious', { width: '120px', padding: '8px', border: '1px solid #888', margin: '8px' })
  put(host, 'div', 'A label that is cut off', { width: '80px', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' })
  const stack = put(host, 'div', '', { position: 'relative', height: '20px' })
  put(stack, 'span', 'First label', { position: 'absolute', left: '0' })
  put(stack, 'span', 'Second label', { position: 'absolute', left: '4px' })
  const row = put(host, 'div', '', { display: 'flex', alignItems: 'flex-start', gap: '8px' })
  put(row, 'button', 'Tall', { height: '40px' })
  put(row, 'button', 'Short', { height: '28px' })
  const target = put(host, 'button', 'Covered', { display: 'block' })
  document.body.prepend(host)
  const at = target.getBoundingClientRect()
  const cover = put(host, 'div', 'Floating', { position: 'fixed', zIndex: '99999', background: '#333', color: '#fff' })
  Object.assign(cover.style, { left: `${String(at.left)}px`, top: `${String(at.top)}px`, width: `${String(at.width)}px`, height: `${String(at.height)}px` })
}

/**
 * Runs in the page. Resolves once nothing that can move a measured box is moving: no scroll container has moved, and no
 * finite animation is running, for 3 frames in a row. Scroll containers are found again on every frame, so one that
 * appears late is watched too. Endless animations and animations inside SVG don't count. A page still moving at the cap is
 * reported, and a timer reports it too if frames stop coming, so the check can never wait forever or pass quietly.
 */
export function stillPage(cap: number): Promise<string> {
  return new Promise((resolve) => {
    let done = false
    const finish = (v: string) => {
      if (!done) {
        done = true
        resolve(v)
      }
    }
    setTimeout(() => finish(`no steady frames within ${String(cap + 500)} ms`), cap + 500)
    const read = () =>
      [document.scrollingElement, ...document.querySelectorAll('*')]
        .filter((el): el is Element => el !== null && (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth))
        .map((el) => `${String(el.scrollTop)},${String(el.scrollLeft)}`)
        .join('|')
    const running = () =>
      document.getAnimations().filter((x) => {
        const target = x.effect && 'target' in x.effect ? (x.effect.target as Element | null) : null
        return x.playState === 'running' && x.effect && x.effect.getTiming().iterations !== Infinity && !target?.closest('svg')
      }).length
    const t0 = performance.now()
    let last = read()
    let calm = 0
    const tick = () => {
      if (done) return
      const now = read()
      const anims = running()
      calm = now === last && !anims ? calm + 1 : 0
      last = now
      if (calm >= 3) {
        finish('')
        return
      }
      if (performance.now() - t0 > cap) {
        finish(`still moving after ${String(cap)} ms${anims ? `, ${String(anims)} animation${anims > 1 ? 's' : ''} running` : ''}`)
        return
      }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

/**
 * Runs in the page. A control a fixed or floating element sits on can't be pressed. Each visible control is scrolled to the
 * bottom edge of the window, where a floating button lives, and its centre is tested for what is drawn there. The scroll
 * position is put back.
 */
export function coverProblems(): Problem[] {
  const name = (el: Element): string => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}` : ''}`
  const controls = [...document.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [role="button"], summary')].filter((el) => {
    if (el.closest('svg, [data-fit-skip]')) return false
    const r = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    return r.width > 1 && r.height > 1 && cs.visibility !== 'hidden' && cs.display !== 'none' && !el.closest('details:not([open]) > :not(summary)')
  })
  const x = window.scrollX
  const y = window.scrollY
  const problems: Problem[] = []
  const seen = new Set<string>()
  for (const el of controls) {
    el.scrollIntoView({ block: 'end', inline: 'nearest', behavior: 'instant' })
    const r = el.getBoundingClientRect()
    if (r.bottom > window.innerHeight + 1 || r.top < 0 || r.right > window.innerWidth + 1 || r.left < 0) continue
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    if (hit && !el.contains(hit) && !hit.contains(el)) {
      const key = `${name(el)}|${name(hit)}`
      if (seen.has(key)) continue
      seen.add(key)
      problems.push({ kind: 'covered', where: name(el), text: `"${(el.textContent ?? el.getAttribute('aria-label') ?? '').replace(/\s+/g, ' ').trim().slice(0, 40)}" is covered by ${name(hit)}` })
    }
  }
  window.scrollTo(x, y)
  return problems
}

/** Waits for the page to stop moving, then measures it. A page that never settles is a problem of its own. */
export async function fitProblems(page: Page): Promise<Problem[]> {
  const moving = await page.evaluate(stillPage, 2000)
  const problems = [...(await page.evaluate(measure)), ...(await page.evaluate(coverProblems))]
  if (moving) problems.push({ kind: 'not settled', where: 'scroll', text: moving })
  return problems
}

export const CONTROL_KINDS: readonly Problem['kind'][] = ['spills', 'cut off', 'overlaps', 'uneven', 'covered']

export function describeProblems(problems: readonly Problem[]): string {
  return problems.map((p) => `${p.kind}: ${p.where}  ${p.text}`).join('\n')
}
