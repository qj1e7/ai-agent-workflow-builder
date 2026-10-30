import { useLayoutEffect, useRef } from 'react'
import { NavigationType, useLocation, useNavigationType } from 'react-router'

const positions = new Map<string, number>()

export function useArrivalScroll(): void {
  const { key } = useLocation()
  const back = useNavigationType() === NavigationType.Pop
  const arrived = useRef(false)

  useLayoutEffect(() => {
    if (arrived.current) return
    arrived.current = true
    const saved = positions.get(key)
    if (!back) window.scrollTo(0, 0)
    else if (saved !== undefined) window.scrollTo(0, saved)
  }, [back, key])

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
