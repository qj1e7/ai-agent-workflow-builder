import type { Track } from '../run'
import { breakPoint, clampLeft, fillScale, orientationOf, parcelPoint, parcelRoom, railBox, type Orientation, type Point } from './geometry'
import styles from './TrackLine.module.css'

/** The route keeps this much room under the line for a panel at 1440, as the template does. A longer panel grows it for the life of the view, so closing the panel never pulls the page up. */
const PANEL_ROOM = 280
const PANEL_MARGIN = 24

/** Where the line's parts were put after a commit: the measured nodes and where the parcel and the fill end. */
export interface Placed {
  readonly o: Orientation
  readonly point: Point | null
  readonly scale: number
}

export function cls(name: string): string {
  return `.${styles[name] ?? name}`
}

export function part(root: ParentNode, name: string): HTMLElement | null {
  return root.querySelector<HTMLElement>(cls(name))
}

/** Layout offsets up to the ancestor: transforms (a figure mid-pop, the parcel mid-travel) never skew them. */
export function offsetIn(el: HTMLElement, ancestor: HTMLElement): Point {
  let x = 0
  let y = 0
  let at: Element | null = el
  while (at instanceof HTMLElement && at !== ancestor) {
    x += at.offsetLeft
    y += at.offsetTop
    at = at.offsetParent
  }
  return { x, y }
}

function centreIn(el: HTMLElement, ancestor: HTMLElement): Point {
  const at = offsetIn(el, ancestor)
  return { x: at.x + el.offsetWidth / 2, y: at.y + el.offsetHeight / 2 }
}

function set(el: HTMLElement, property: string, value: string): void {
  if (el.style.getPropertyValue(property) !== value) el.style.setProperty(property, value)
}

export function px(n: number): string {
  return `${Math.round(n * 10) / 10}px`
}

export function translate(point: Point, el: HTMLElement): string {
  return `translate(${px(point.x - el.offsetWidth / 2)}, ${px(point.y - el.offsetHeight / 2)})`
}

export function scaleOf(o: Orientation, scale: number): string {
  return `${o === 'horizontal' ? 'scaleX' : 'scaleY'}(${Math.round(scale * 10000) / 10000})`
}

/**
 * Places what hangs off the measured nodes: the rail, the fill up to the parcel, the parcel, the break, the bubble
 * and the panel. Reads layout once per commit and writes a style only when it changed. The 760 px breakpoint stays
 * in CSS: the orientation is read back from where the nodes landed.
 */
export function place(route: HTMLElement, track: Track): Placed {
  const stops = [...route.querySelectorAll<HTMLElement>('[data-stop]')]
  const nodes = stops.map((li) => {
    const node = li.querySelector<HTMLElement>('[data-node]')
    return node ? centreIn(node, route) : { x: 0, y: 0 }
  })
  const o = orientationOf(nodes)
  const rail = part(route, 'rail')
  const fill = part(route, 'fill')
  const parcel = route.querySelector<HTMLElement>('[data-parcel]')
  const brk = part(route, 'break')

  const box = railBox(nodes, o)
  for (const el of [rail, fill]) {
    if (!el || !box) continue
    set(el, 'left', px(box.left))
    set(el, 'top', px(box.top))
    set(el, 'width', px(box.width))
    set(el, 'height', px(box.height))
  }
  const point = track.parcel ? parcelPoint(nodes, o, track.parcel.at, track.parcel.before) : null
  const scale = fillScale(nodes, o, point)
  if (fill) set(fill, 'transform', scaleOf(o, scale))
  if (parcel && point && track.parcel) {
    const column = stops[track.parcel.at]?.offsetWidth
    fitParcel(parcel, o === 'horizontal' && column !== undefined ? parcelRoom(column, track.parcel.before) : null)
    set(parcel, 'transform', translate(point, parcel))
  }
  const snap = track.breakAt === null ? null : breakPoint(nodes, o, track.breakAt)
  if (brk && snap) {
    set(brk, 'left', px(snap.x))
    set(brk, 'top', px(snap.y))
  }
  placeSlots(route, stops, o, track)
  return { o, point, scale }
}

/** Full size while the parcel fits its room, else the compact form: its icon and a few words. The phone draws a circle. */
function fitParcel(parcel: HTMLElement, room: number | null): void {
  const narrow = styles['narrow'] ?? 'narrow'
  parcel.classList.remove(narrow)
  if (room === null) return
  set(parcel, '--room', px(room))
  const body = parcel.querySelector<HTMLElement>(`${cls('shaker')} > ${cls('pbody')}`)
  if (body && body.offsetWidth > room) parcel.classList.add(narrow)
}

/** At 1440 the bubble aims at its speaker and the panel centres on its stop, both kept inside the route. On the phone CSS places both. */
function placeSlots(route: HTMLElement, stops: readonly HTMLElement[], o: Orientation, track: Track): void {
  const width = route.clientWidth
  let panelBottom = 0
  for (const li of stops) {
    const liAt = offsetIn(li, route)
    const above = li.querySelector<HTMLElement>(`:scope > ${cls('slotAbove')}`)
    if (above) {
      if (o === 'vertical') {
        set(above, 'left', '')
        above.style.removeProperty('--tail')
      } else {
        const speaker = track.speech ? li.querySelector<HTMLElement>(`[data-figure="agent:${track.speech.speaker}"]`) : null
        const centre = liAt.x + (speaker ? offsetIn(speaker, li).x + speaker.offsetWidth / 2 : li.offsetWidth / 2)
        const w = above.offsetWidth
        const left = clampLeft(centre, w, 0, width)
        set(above, 'left', px(left + w / 2 - liAt.x))
        set(above, '--tail', px(centre - left))
      }
    }
    const below = li.querySelector<HTMLElement>(`:scope > ${cls('slotBelow')}`)
    if (below) {
      if (o === 'vertical') {
        set(below, 'left', '')
      } else {
        const w = below.offsetWidth
        const left = clampLeft(liAt.x + li.offsetWidth / 2, w, 0, width)
        set(below, 'left', px(left + w / 2 - liAt.x))
        panelBottom = Math.max(panelBottom, liAt.y + below.offsetTop + below.offsetHeight)
      }
    }
  }
  const list = stops[0]?.parentElement
  const listBottom = list ? list.offsetTop + list.offsetHeight : 0
  const need = panelBottom + PANEL_MARGIN - listBottom
  if (o === 'vertical') set(route, 'padding-bottom', '')
  else if (need > Math.max(PANEL_ROOM, parseFloat(route.style.paddingBottom) || 0)) set(route, 'padding-bottom', px(need))
}

/** Calls replace when the route resizes or the web font arrives, until the returned stop is called. */
export function followLayout(route: HTMLElement, replace: () => void, fontsReady: Promise<unknown> = document.fonts.ready): () => void {
  let alive = true
  const observer = new ResizeObserver(replace)
  observer.observe(route)
  void fontsReady.then(() => {
    if (alive) replace()
  })
  return () => {
    alive = false
    observer.disconnect()
  }
}
