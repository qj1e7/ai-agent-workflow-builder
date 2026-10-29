const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

export function motionAllowed(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && !window.matchMedia(REDUCED_MOTION).matches
}
