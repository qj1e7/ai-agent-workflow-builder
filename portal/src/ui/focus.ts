import { useCallback, useEffect, useRef } from 'react'

/**
 * Moves focus once to an element that replaces the control a person just used, such as what a decision turned into.
 * Call the returned arm() when the action succeeds; focus moves on the first render where `ready` holds.
 */
export function useFocusWhenReady(ready: boolean, target: () => HTMLElement | null | undefined): () => void {
  const armed = useRef(false)
  useEffect(() => {
    if (!armed.current || !ready) return
    armed.current = false
    target()?.focus()
  })
  return useCallback(() => {
    armed.current = true
  }, [])
}

export function placeAfterRedraw<T>(order: readonly T[], pressed: T, shown: readonly T[]): T | null {
  if (shown.includes(pressed)) return pressed
  const at = order.indexOf(pressed)
  const nearest = [...order.slice(at + 1), ...order.slice(0, at).reverse()]
  return nearest.find((place) => shown.includes(place)) ?? null
}

/**
 * Call the returned function with the pressed control's place as a press makes the page read again. When the answer is
 * drawn (`answeredAt` moves) and focus fell to the body because the redraw removed that control, focus follows
 * placeAfterRedraw to the element with the matching data-place, or to the page heading.
 */
export function useFocusAfterReread<T extends string>(order: readonly T[], shown: readonly T[], answeredAt: number): (pressed: T) => void {
  const armed = useRef<{ readonly pressed: T; readonly answeredAt: number } | null>(null)
  const drawn = useRef(answeredAt)
  useEffect(() => {
    drawn.current = answeredAt
    const press = armed.current
    if (!press || press.answeredAt === answeredAt) return
    armed.current = null
    if (document.activeElement && document.activeElement !== document.body) return
    const place = placeAfterRedraw(order, press.pressed, shown)
    document.querySelector<HTMLElement>(place === null ? 'main h1' : `main [data-place="${place}"]`)?.focus()
  })
  return useCallback((pressed: T) => {
    armed.current = { pressed, answeredAt: drawn.current }
  }, [])
}
