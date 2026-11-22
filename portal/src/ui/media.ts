import { useSyncExternalStore } from 'react'

/** Whether the window matches a media query, such as '(max-width: 900px)'. Without matchMedia, as in a test, it never matches. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      if (typeof window.matchMedia !== 'function') return () => undefined
      const list = window.matchMedia(query)
      list.addEventListener('change', notify)
      return () => list.removeEventListener('change', notify)
    },
    () => typeof window.matchMedia === 'function' && window.matchMedia(query).matches,
    () => false,
  )
}

/** At 900 px and narrower the side panel covers the window (ADR 0043). The rail turns into a bar at 860 px, in its own stylesheet (ADR 0052). */
export const NARROW = '(max-width: 900px)'
