import type { BeatPlan, TimedAct, Track } from '../run'
import type { Box, Orientation, Point } from './geometry'
import { cls, offsetIn, part, px, scaleOf, translate, type Placed } from './place'

export interface Scene {
  readonly track: Track
  readonly plan: BeatPlan | null
  readonly reduced: boolean
}

/**
 * Plays each beat's acts once per beat key, as Web Animations on transform and opacity. React has already drawn the
 * frame's final state and place() has put the parts there, so every animation runs into that state and cancelling
 * one is always safe. A part the commit removed (a figure that left, the parcel's old form, the arm's old stripes)
 * is faded out where it stood.
 */
export interface Motion {
  update(this: void, route: HTMLElement, scene: Scene, placed: Placed): void
  reset(this: void): void
}

const EASE = 'cubic-bezier(.5, 0, .2, 1)'
const EASE_ARM = 'cubic-bezier(.3, 1.2, .45, 1)'
/** Under reduced motion an appearing part fades in this long, at once. Nothing travels, turns or nods. */
const FADE_MS = 200
const GLIDE_MS = 360
const CUT_MS = 260

const POP: Keyframe[] = [
  { opacity: 0, transform: 'scale(.6)' },
  { opacity: 1, transform: 'none' },
]
const RISE: Keyframe[] = [
  { opacity: 0, transform: 'translateY(8px)' },
  { opacity: 1, transform: 'none' },
]
const SWAP: Keyframe[] = [
  { opacity: 0, transform: 'scale(.88)' },
  { opacity: 1, transform: 'none' },
]
const SNAP: Keyframe[] = [
  { opacity: 0, transform: 'scale(.3)' },
  { opacity: 1, transform: 'none' },
]
const NOD: Keyframe[] = [{ transform: 'none' }, { transform: 'translateY(-5px)', offset: 0.4 }, { transform: 'none' }]
const SHAKE: Keyframe[] = [
  { transform: 'none' },
  { transform: 'translateX(-5px)', offset: 0.2 },
  { transform: 'translateX(5px)', offset: 0.4 },
  { transform: 'translateX(-3px)', offset: 0.6 },
  { transform: 'translateX(3px)', offset: 0.8 },
  { transform: 'none' },
]
const FADE_IN: Keyframe[] = [{ opacity: 0 }, { opacity: 1 }]
const FADE_OUT: Keyframe[] = [{ opacity: 1 }, { opacity: 0 }]
const DIP: Keyframe[] = [{ opacity: 0.35 }, { opacity: 1 }]

interface Timing {
  readonly delayMs: number
  readonly durationMs: number
}

const AT_ONCE: Timing = { delayMs: 0, durationMs: FADE_MS }

interface FigureSeen {
  readonly el: HTMLElement
  /** Inside its stop, so a stop that moves down on the phone does not read as the figure moving. */
  readonly inStop: Point
  /** Inside the route, where a ghost of it is placed. */
  readonly box: Box
}

/** What a commit drew, so the next beat can animate from it. */
interface Seen {
  readonly figures: ReadonlyMap<string, FigureSeen>
  readonly fills: ReadonlyMap<string, Element>
  readonly captions: ReadonlyMap<string, Element>
  readonly body: Element | null
  readonly stripes: Element | null
  readonly ring: Element | null
  readonly parcel: Point | null
  readonly fill: number
}

const NOTHING_SEEN: Seen = { figures: new Map(), fills: new Map(), captions: new Map(), body: null, stripes: null, ring: null, parcel: null, fill: 0 }

interface Cue {
  readonly route: HTMLElement
  readonly track: Track
  readonly reduced: boolean
  readonly o: Orientation
  readonly parcel: HTMLElement | null
  readonly fill: HTMLElement | null
  readonly point: Point | null
  readonly scale: number
  /** Where the parcel and the fill stood on screen when the beat began, mid-flight included. */
  readonly from: { readonly parcel: Point | null; readonly fill: number }
  readonly before: Seen
  readonly now: Seen
}

/** A direct child, so a ghost of the same part sitting in its slot is never mistaken for the live one. */
function child(parent: Element | null, name: string): HTMLElement | null {
  return parent?.querySelector<HTMLElement>(`:scope > ${cls(name)}`) ?? null
}

function stopKeyAt(track: Track, index: number): string {
  return track.stops[index]?.key ?? ''
}

export function createMotion(): Motion {
  let played: string | null = null
  let running: Animation[] = []
  let ghosts: Element[] = []
  let seen: Seen = NOTHING_SEEN

  function clear(): void {
    for (const animation of running) animation.cancel()
    for (const ghost of ghosts) ghost.remove()
    running = []
    ghosts = []
  }

  function animate(el: Element | null | undefined, frames: Keyframe[], t: Timing, easing = EASE, fill: FillMode = 'backwards'): void {
    if (!el || t.durationMs <= 0) return
    running.push(el.animate(frames, { delay: t.delayMs, duration: t.durationMs, easing, fill }))
  }

  /** The part's place on screen belongs to an animation now, not to its style. */
  function inFlight(el: Element): boolean {
    return running.some((animation) => {
      const effect = animation.effect
      return effect instanceof KeyframeEffect && effect.target === el && animation.playState !== 'finished' && effect.getComputedTiming().progress !== null
    })
  }

  /** An appearing part: its own motion, or a short fade at once under reduced motion. Hidden until its act. */
  function appear(c: Cue, el: Element | null | undefined, frames: Keyframe[], t: Timing): void {
    if (c.reduced) animate(el, FADE_IN, AT_ONCE)
    else animate(el, frames, t)
  }

  /** The element the last commit drew and this one removed, faded out where it stood. */
  function ghost(c: Cue, el: Element | null, into: HTMLElement | null, t: Timing, at?: Box): void {
    if (c.reduced || !el || el.isConnected || !into || !(el instanceof HTMLElement)) return
    el.removeAttribute('data-figure')
    el.removeAttribute('data-status')
    if (at) {
      el.style.position = 'absolute'
      el.style.margin = '0'
      el.style.left = px(at.left)
      el.style.top = px(at.top)
      el.style.width = px(at.width)
      el.style.height = px(at.height)
    }
    into.append(el)
    ghosts.push(el)
    animate(el, FADE_OUT, t, EASE, 'both')
  }

  function stopEl(c: Cue, index: number): HTMLElement | null {
    return c.route.querySelector<HTMLElement>(`[data-stop="${stopKeyAt(c.track, index)}"]`)
  }

  function figureEl(c: Cue, index: number, figure: string): HTMLElement | null {
    return stopEl(c, index)?.querySelector<HTMLElement>(`[data-figure="${figure}"]`) ?? null
  }

  function act(c: Cue, timed: TimedAct): void {
    const a = timed.act
    switch (a.what) {
      case 'relayout':
        animate(c.route, DIP, c.reduced ? AT_ONCE : timed)
        return
      case 'leave': {
        const was = c.before.figures.get(`${stopKeyAt(c.track, a.stop)}|${a.figure}`)
        if (was) ghost(c, was.el, part(c.route, 'ghosts'), timed, was.box)
        return
      }
      case 'arrive':
        appear(c, figureEl(c, a.stop, a.figure), POP, timed)
        return
      case 'nod':
        if (!c.reduced) animate(figureEl(c, a.stop, a.figure)?.querySelector(cls('av')), NOD, timed)
        return
      case 'arm': {
        const arm = part(c.route, 'arm')
        if (!arm) return
        appear(c, child(arm, 'stripes'), FADE_IN, timed)
        ghost(c, c.before.stripes, child(arm, 'armGhost'), timed)
        const housing = part(c.route, 'housing')
        appear(c, child(housing, 'ring'), FADE_IN, timed)
        ghost(c, c.before.ring, child(housing, 'ringGhost'), timed)
        const angle = (state: string) => (state === 'open' ? -90 : 0)
        if (!c.reduced && angle(a.from) !== angle(a.to)) {
          animate(arm, [{ transform: `rotate(${angle(a.from)}deg)` }, { transform: `rotate(${angle(a.to)}deg)` }], timed, EASE_ARM)
        }
        return
      }
      case 'node': {
        const key = stopKeyAt(c.track, a.stop)
        const fill = c.now.fills.get(key)
        if (fill && fill !== c.before.fills.get(key)) appear(c, fill, POP, timed)
        return
      }
      case 'travel': {
        const { parcel, point, fill } = c
        if (!parcel || !point) return
        const to = translate(point, parcel)
        if (a.from === null || c.from.parcel === null) {
          appear(c, parcel, [{ opacity: 0, transform: `${to} scale(.6)` }, { opacity: 1, transform: to }], timed)
          return
        }
        if (c.reduced) return
        animate(parcel, [{ transform: translate(c.from.parcel, parcel) }, { transform: to }], timed)
        animate(fill, [{ transform: scaleOf(c.o, c.from.fill) }, { transform: scaleOf(c.o, c.scale) }], timed)
        return
      }
      case 'form': {
        const shaker = child(c.parcel, 'shaker')
        appear(c, child(shaker, 'pbody'), SWAP, timed)
        ghost(c, c.before.body, child(shaker, 'parcelGhost'), { delayMs: timed.delayMs, durationMs: Math.round(timed.durationMs * 0.6) })
        if (a.shake && !c.reduced) animate(shaker, SHAKE, timed)
        return
      }
      case 'break':
        appear(c, part(c.route, 'break'), SNAP, timed)
        return
      case 'speech':
        appear(c, stopEl(c, a.stop)?.querySelector(cls('bubble')), RISE, timed)
        return
      case 'panel':
        appear(c, stopEl(c, a.stop)?.querySelector(cls('slotBelow'))?.firstElementChild, RISE, timed)
        return
    }
  }

  /** A figure that stays while another leaves or arrives slides to its new place instead of jumping. */
  function glide(plan: BeatPlan, c: Cue): void {
    for (const [key, now] of c.now.figures) {
      const was = c.before.figures.get(key)
      if (was?.el !== now.el) continue
      const dx = was.inStop.x - now.inStop.x
      const dy = was.inStop.y - now.inStop.y
      if (Math.abs(dx) + Math.abs(dy) < 1) continue
      const stop = key.slice(0, key.indexOf('|'))
      const cue = plan.acts.find(({ act: a }) => (a.what === 'leave' || a.what === 'arrive') && stopKeyAt(c.track, a.stop) === stop)
      const t = cue ? { delayMs: cue.delayMs, durationMs: Math.max(cue.durationMs, GLIDE_MS) } : { delayMs: 0, durationMs: GLIDE_MS }
      animate(now.el, [{ transform: `translate(${px(dx)}, ${px(dy)})` }, { transform: 'none' }], t)
    }
  }

  /**
   * A stop's new words fade in with the first act that changes that stop (its node, the arm, the parcel's new form,
   * the break), so a caption never runs ahead of the motion it describes.
   */
  function captions(plan: BeatPlan, c: Cue): void {
    const cues = new Map<number, TimedAct>()
    for (const timed of plan.acts) {
      const a = timed.act
      const stop = a.what === 'node' || a.what === 'arm' || a.what === 'break' ? a.stop : a.what === 'form' ? (c.track.parcel?.at ?? null) : null
      if (stop !== null && !cues.has(stop)) cues.set(stop, timed)
    }
    for (const [stop, timed] of cues) {
      const key = stopKeyAt(c.track, stop)
      const now = c.now.captions.get(key)
      if (now && now !== c.before.captions.get(key)) appear(c, now, FADE_IN, timed)
    }
  }

  function play(plan: BeatPlan, c: Cue): void {
    if (plan.entry === 'cut') animate(c.route, DIP, c.reduced ? AT_ONCE : { delayMs: 0, durationMs: CUT_MS })
    for (const timed of plan.acts) act(c, timed)
    captions(plan, c)
    if (!c.reduced) glide(plan, c)
  }

  function update(route: HTMLElement, { track, plan, reduced }: Scene, { o, point, scale }: Placed): void {
    const parcel = route.querySelector<HTMLElement>('[data-parcel]')
    const fill = part(route, 'fill')
    const now = record(route, track, point, scale)
    const key = plan?.key ?? null
    if (key !== played) {
      const from = {
        parcel: parcel && inFlight(parcel) ? visualCentre(parcel, route) : seen.parcel,
        fill: fill && inFlight(fill) ? visualScale(fill, o) : seen.fill,
      }
      clear()
      played = key
      if (plan) play(plan, { route, track, reduced, o, parcel, fill, point, scale, from, before: seen, now })
    }
    seen = now
  }

  return {
    update,
    reset() {
      clear()
      played = null
    },
  }
}

function visualCentre(el: HTMLElement, route: HTMLElement): Point {
  const r = route.getBoundingClientRect()
  const b = el.getBoundingClientRect()
  return { x: b.left + b.width / 2 - r.left, y: b.top + b.height / 2 - r.top }
}

function visualScale(el: HTMLElement, o: Orientation): number {
  const matrix = new DOMMatrixReadOnly(getComputedStyle(el).transform)
  return o === 'horizontal' ? matrix.a : matrix.d
}

function record(route: HTMLElement, track: Track, parcel: Point | null, fill: number): Seen {
  const figures = new Map<string, FigureSeen>()
  const fills = new Map<string, Element>()
  const captions = new Map<string, Element>()
  route.querySelectorAll<HTMLElement>('[data-stop]').forEach((li, index) => {
    const key = stopKeyAt(track, index)
    for (const el of li.querySelectorAll<HTMLElement>('[data-figure]')) {
      const at = offsetIn(el, route)
      figures.set(`${key}|${el.dataset['figure'] ?? ''}`, {
        el,
        inStop: offsetIn(el, li),
        box: { left: at.x, top: at.y, width: el.offsetWidth, height: el.offsetHeight },
      })
    }
    const nodeFill = li.querySelector(`[data-node] > ${cls('nodeFill')}`)
    if (nodeFill) fills.set(key, nodeFill)
    const caption = li.querySelector(cls('capIn'))
    if (caption) captions.set(key, caption)
  })
  return {
    figures,
    fills,
    captions,
    body: child(route.querySelector(`[data-parcel] > ${cls('shaker')}`), 'pbody'),
    stripes: child(route.querySelector(cls('arm')), 'stripes'),
    ring: child(route.querySelector(cls('housing')), 'ring'),
    parcel,
    fill,
  }
}
