import { useCallback } from 'react'

/**
 * A ref for a container whose loops should rest while nobody can see them. It sets data-paused when the container
 * is scrolled out of view or the tab is hidden, and the face and dot styles pause under it.
 */
export function usePauseUnseen(): (node: HTMLElement | null) => (() => void) | undefined {
  return useCallback((node: HTMLElement | null) => {
    if (!node) return undefined
    let inView = true
    const apply = () => node.toggleAttribute('data-paused', !inView || document.hidden)
    const watch =
      typeof IntersectionObserver === 'function'
        ? new IntersectionObserver((entries) => {
            inView = entries.some((entry) => entry.isIntersecting)
            apply()
          })
        : null
    watch?.observe(node)
    document.addEventListener('visibilitychange', apply)
    apply()
    return () => {
      watch?.disconnect()
      document.removeEventListener('visibilitychange', apply)
    }
  }, [])
}
