import { useLayoutEffect, useRef } from 'react'
import { NavigationType, useLocation, useNavigationType } from 'react-router'

const positions = new Map<string, number>()

/**
 * A page opened by a link starts at the top. Back or Forward puts it where it was, once its content has drawn, so the
 * list a person came back to is at the row they left.
 */
export function useArrivalScroll(ready: boolean): void {
  const { key } = useLocation()
  const back = useNavigationType() === NavigationType.Pop
  const arrived = useRef(false)

  useLayoutEffect(() => {
    if (arrived.current || !ready) return
    arrived.current = true
    const saved = positions.get(key)
    if (!back) window.scrollTo(0, 0)
    else if (saved !== undefined) window.scrollTo(0, saved)
  }, [ready, back, key])

  /** A layout effect, so it lets go before the next page scrolls to its top. */
  useLayoutEffect(() => {
    let y = window.scrollY
    const save = () => {
      y = window.scrollY
    }
    window.addEventListener('scroll', save, { passive: true })
    return () => {
      window.removeEventListener('scroll', save)
      positions.set(key, y)
    }
  }, [key])
}
