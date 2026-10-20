export interface MovingAnimation {
  name: string
  target: string
  properties: string[]
}

const MOVING_PROPERTIES = ['transform', 'translate', 'rotate', 'scale', 'offsetDistance', 'offsetPath', 'offsetRotate']

// Runs inside the page. An animation moves something when a transform-like property takes more than one value across its keyframes.
export function movingAnimations(properties: string[]): MovingAnimation[] {
  const describe = (el: Element | null): string => {
    if (!el) return 'unknown'
    const cls = typeof el.className === 'string' && el.className ? `.${el.className.split(/\s+/)[0]}` : ''
    return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${cls}`
  }
  const found: MovingAnimation[] = []
  for (const animation of document.getAnimations()) {
    if (animation.playState !== 'running') continue
    const effect = animation.effect as KeyframeEffect | null
    const frames = effect?.getKeyframes?.() ?? []
    const moving = properties.filter((property) => {
      const values = new Set(
        frames.map((frame) => {
          const value = (frame as unknown as Record<string, unknown>)[property]
          return typeof value === 'string' || typeof value === 'number' ? String(value) : 'none'
        }),
      )
      return values.size > 1
    })
    if (moving.length > 0) {
      const name = 'animationName' in animation ? String((animation as CSSAnimation).animationName) : 'transitionProperty' in animation ? `transition ${String((animation as CSSTransition).transitionProperty)}` : 'web animation'
      found.push({ name, target: describe(effect?.target ?? null), properties: moving })
    }
  }
  return found
}

export const MOVING = MOVING_PROPERTIES
