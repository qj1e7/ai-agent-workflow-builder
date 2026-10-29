const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

/** False under reduced motion, where nothing travels and nothing waits for an animation. */
export function motionAllowed(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && !window.matchMedia(REDUCED_MOTION).matches
}
