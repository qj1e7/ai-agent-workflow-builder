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
