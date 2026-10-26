import { useEffect, useState } from 'react'
import type { TourStep } from './quests'
import { stopSelector, type TourStop } from './stops'
import { alreadyMet, type Who } from './tourState'

export interface Box {
  readonly top: number
  readonly left: number
  readonly width: number
  readonly height: number
}

export type Side = 'right' | 'left'

const GLOW_ROOM = 16

/** The card's widest size, so the card can move aside before it covers the stop it points at. */
const CARD_ROOM = { width: 392, height: 470 }

/** The first element marked with the stop that is on screen. A stop can be marked twice, as the top menu and the phone tab bar are. */
export function shownElement(stop: TourStop): HTMLElement | null {
  for (const element of document.querySelectorAll<HTMLElement>(stopSelector(stop))) {
    if (element.getClientRects().length > 0) return element
  }
  return null
}

function boxOf(rect: DOMRect): Box {
  return { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
}

function sameBox(a: Box | null, b: Box | null): boolean {
  if (a === null || b === null) return a === b
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height
}

/** The card sits bottom right, unless something it must not cover is under it there and the left is free. */
export function sideFor(boxes: readonly (Box | null)[], viewport: { width: number; height: number }): Side {
  const shown = boxes.filter((box): box is Box => box !== null)
  const below = (box: Box) => box.top + box.height > viewport.height - CARD_ROOM.height
  const underRight = shown.some((box) => below(box) && box.left + box.width > viewport.width - CARD_ROOM.width)
  const underLeft = shown.some((box) => below(box) && box.left < CARD_ROOM.width)
  return underRight && !underLeft ? 'left' : 'right'
}

/** Scrolls the stop into the room between the header and the card. On a phone the card spans the bottom, so the room ends above it. */
function bringIntoView(element: HTMLElement, reduced: boolean): void {
  const rect = element.getBoundingClientRect()
  const top = document.querySelector('header')?.getBoundingClientRect().bottom ?? 0
  const card = document.querySelector('[data-tour-card]')?.getBoundingClientRect()
  const bottom = card && card.width > window.innerWidth * 0.8 ? card.top : window.innerHeight
  const room = bottom - top
  const behavior = reduced ? 'auto' : 'smooth'
  if (rect.height > room * 0.8) {
    if (rect.top >= top && rect.top <= top + room / 2) return
    window.scrollBy({ top: rect.top - top - 16, behavior })
    return
  }
  // The glow ring sits just outside the stop, so the stop needs a little room on each side to show whole.
  if (rect.top >= top + GLOW_ROOM && rect.bottom <= bottom - GLOW_ROOM) return
  window.scrollBy({ top: rect.top + rect.height / 2 - (top + room / 2), behavior })
}

interface Placed {
  readonly stop: TourStop
  readonly box: Box | null
  readonly side: Side
}

/**
 * Follows the stop on screen every frame, as the page scrolls and changes, and brings it into view the first time it
 * shows. The card's side keeps both the stop and keepClear uncovered when it can.
 */
export function useStop(stop: TourStop | undefined, keepClear: TourStop | undefined, reduced: boolean): { box: Box | null; side: Side } {
  const [placed, setPlaced] = useState<Placed | null>(null)
  useEffect(() => {
    if (!stop) return
    let frame = 0
    let seen = false
    const follow = () => {
      const element = shownElement(stop)
      if (element && !seen) {
        seen = true
        bringIntoView(element, reduced)
      }
      const box = element ? boxOf(element.getBoundingClientRect()) : null
      const clear = keepClear ? shownElement(keepClear) : null
      const side = sideFor([box, clear ? boxOf(clear.getBoundingClientRect()) : null], { width: window.innerWidth, height: window.innerHeight })
      setPlaced((previous) =>
        previous?.stop === stop && previous.side === side && sameBox(previous.box, box) ? previous : { stop, box, side },
      )
      frame = requestAnimationFrame(follow)
    }
    frame = requestAnimationFrame(follow)
    return () => cancelAnimationFrame(frame)
  }, [stop, keepClear, reduced])
  return placed && placed.stop === stop ? placed : { box: null, side: 'right' }
}

/**
 * Calls met with the step's id once the person has done it: reached the page, become the right user, pressed the stop,
 * or made the stop appear. A step to read is met only by its Next button.
 */
export function useStepMet(step: TourStep | null, pathname: string, who: Who | null, met: (id: string) => void): void {
  useEffect(() => {
    if (step && alreadyMet(step.done, pathname, who)) met(step.id)
  }, [step, pathname, who, met])

  useEffect(() => {
    if (!step) return
    const { done, id } = step
    if (done.kind === 'press') {
      const selector = stopSelector(done.stop)
      // A change counts too, so a radio picked with the arrow keys meets the step.
      const onPress = (event: Event) => {
        if (event.target instanceof Element && event.target.closest(selector)) met(id)
      }
      document.addEventListener('click', onPress, true)
      document.addEventListener('change', onPress, true)
      return () => {
        document.removeEventListener('click', onPress, true)
        document.removeEventListener('change', onPress, true)
      }
    }
    if (done.kind === 'see') {
      const stop = done.stop
      const look = () => {
        if (shownElement(stop)) met(id)
      }
      const observer = new MutationObserver(look)
      observer.observe(document.body, { childList: true, subtree: true })
      const first = requestAnimationFrame(look)
      return () => {
        cancelAnimationFrame(first)
        observer.disconnect()
      }
    }
  }, [step, met])
}
