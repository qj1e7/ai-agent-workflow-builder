import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { motionAllowed } from './motion'

export interface Present<T> {
  readonly key: string
  readonly item: T
  readonly leaving: boolean
}

export function presentNow<T>(items: readonly T[], keyOf: (item: T) => string): Present<T>[] {
  return items.map((item) => ({ key: keyOf(item), item, leaving: false }))
}

/** The list as it is now, with each item that left kept at its old place and marked leaving until it is gone. */
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

interface Shown<T> {
  readonly items: readonly T[]
  readonly list: readonly Present<T>[]
}

/**
 * A removed item stays drawn, marked leaving, so it can fade out before the list closes the gap. Call gone(key) when
 * its fade ends. With reduced motion it goes at once.
 */
export function usePresence<T>(items: readonly T[], keyOf: (item: T) => string): { readonly list: readonly Present<T>[]; readonly gone: (key: string) => void } {
  const [shown, setShown] = useState<Shown<T>>(() => ({ items, list: presentNow(items, keyOf) }))
  let list = shown.list
  if (shown.items !== items) {
    list = motionAllowed() ? withLeaving(shown.list, items, keyOf) : presentNow(items, keyOf)
    setShown({ items, list })
  }
  const gone = useCallback((key: string) => setShown((now) => ({ ...now, list: withoutGone(now.list, key) })), [])
  return { list, gone }
}

const GLIDE_MS = 220
const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)'

/** Each child marked data-glide that moved since the last render glides from where it was, so the list never jumps. */
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
