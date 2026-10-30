import { useLayoutEffect, useRef, useState, type AnimationEvent, type RefObject } from 'react'
import { motionAllowed } from './motion'

export interface Present<T> {
  readonly key: string
  readonly item: T
  readonly leaving: boolean
}

export function presentNow<T>(items: readonly T[], keyOf: (item: T) => string): Present<T>[] {
  return items.map((item) => ({ key: keyOf(item), item, leaving: false }))
}

export function withLeaving<T>(before: readonly Present<T>[], items: readonly T[], keyOf: (item: T) => string): Present<T>[] {
  const now = presentNow(items, keyOf)
  const kept = new Set(now.map((present) => present.key))
  before.forEach((old, index) => {
    if (!kept.has(old.key)) now.splice(Math.min(index, now.length), 0, { ...old, leaving: true })
  })
  return now
}

export function withoutGone<T>(list: readonly Present<T>[], key: string): Present<T>[] {
  return list.filter((present) => !(present.leaving && present.key === key))
}

interface Drawn<T> {
  readonly items: readonly T[]
  readonly list: readonly Present<T>[]
}

export interface Shown<T> extends Present<T> {
  readonly onAnimationEnd: ((event: AnimationEvent) => void) | undefined
}

export function usePresence<T>(items: readonly T[], keyOf: (item: T) => string): readonly Shown<T>[] {
  const [drawn, setDrawn] = useState<Drawn<T>>(() => ({ items, list: presentNow(items, keyOf) }))
  let list = drawn.list
  if (drawn.items !== items) {
    list = motionAllowed() ? withLeaving(drawn.list, items, keyOf) : presentNow(items, keyOf)
    setDrawn({ items, list })
  }
  const fadedOut = (key: string) => (event: AnimationEvent) => {
    if (event.target === event.currentTarget) setDrawn((now) => ({ ...now, list: withoutGone(now.list, key) }))
  }
  return list.map((present) => ({ ...present, onAnimationEnd: present.leaving ? fadedOut(present.key) : undefined }))
}

const GLIDE_MS = 220
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'

export function useGlide(container: RefObject<HTMLElement | null>): void {
  const tops = useRef(new Map<string, number>())
  useLayoutEffect(() => {
    const children = [...(container.current?.querySelectorAll<HTMLElement>(':scope > [data-glide]') ?? [])]
    const before = tops.current
    tops.current = new Map(children.map((child) => [child.dataset['glide'] ?? '', child.offsetTop]))
    if (!motionAllowed()) return
    for (const child of children) {
      const was = before.get(child.dataset['glide'] ?? '')
      const moved = was === undefined ? 0 : was - child.offsetTop
      if (Math.abs(moved) > 1) child.animate([{ transform: `translateY(${moved}px)` }, { transform: 'none' }], { duration: GLIDE_MS, easing: EASE_OUT })
    }
  })
}
