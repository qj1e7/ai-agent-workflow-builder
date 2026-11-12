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

/** The one breakpoint (spec 3.4): at 900 px and narrower the rail is a bar across the top and the side panel covers the window. */
export const NARROW = '(max-width: 900px)'
