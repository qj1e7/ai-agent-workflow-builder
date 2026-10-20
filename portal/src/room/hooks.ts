import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type RefObject } from 'react'
import { runId, useLiveView, type LiveView, type WhenFinished } from '../run'
import { AGENTS } from './registry'

export function useLiveRoom(id: string, whenFinished: WhenFinished, openingMs = 0): LiveView {
  return useLiveView(runId(id), { whenFinished, registry: AGENTS, openingMs })
}

/** The element's content width, kept current by a ResizeObserver. 0 until the first measurement. */
export function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => setWidth(Math.round(element.getBoundingClientRect().width))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return width
}

const REDUCED = '(prefers-reduced-motion: reduce)'

function subscribeMotion(listener: () => void): () => void {
  const query = window.matchMedia(REDUCED)
  query.addEventListener('change', listener)
  return () => query.removeEventListener('change', listener)
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, () => window.matchMedia(REDUCED).matches, () => false)
}

const TECHNICAL_KEY = 'portal.technical-details'

function readTechnical(): boolean {
  try {
    return window.localStorage.getItem(TECHNICAL_KEY) === 'on'
  } catch {
    return false
  }
}

export function useTechnicalDetails(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(readTechnical)
  const set = (next: boolean) => {
    setOn(next)
    try {
      window.localStorage.setItem(TECHNICAL_KEY, next ? 'on' : 'off')
    } catch {
      // The choice still holds for this page when storage is blocked.
    }
  }
  return [on, set]
}

/** Runs a Web Animation on the element once per key, so a beat animates exactly once and a replay of the same seq animates again. */
export interface AnimationPlan {
  readonly keyframes: Keyframe[]
  readonly options: KeyframeAnimationOptions
}

/** A plan, or a function that measures the laid-out element to make one. */
type PlanOf<E> = AnimationPlan | ((element: E) => AnimationPlan | null)

export function useBeatAnimation<E extends HTMLElement | SVGElement>(
  ref: RefObject<E | null>,
  key: string | null,
  plan: PlanOf<E> | null,
  enabled: boolean,
): void {
  const planRef = useRef<PlanOf<E> | null>(null)
  useEffect(() => {
    planRef.current = plan
  })
  useEffect(() => {
    const element = ref.current
    const current = planRef.current
    if (!element || !current || key === null || !enabled) return
    const resolved = typeof current === 'function' ? current(element) : current
    if (!resolved) return
    const animation = element.animate(resolved.keyframes, resolved.options)
    return () => animation.cancel()
  }, [ref, key, enabled])
}
