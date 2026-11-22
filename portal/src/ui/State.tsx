import type { HTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'
import styles from './State.module.css'

/**
 * A state's colour, one meaning each (ADR 0052): ok and on are fine, run is at work right now, wait needs a person, stop has
 * stopped, and off is paused, a draft, declined or not reached.
 */
export type StateTone = 'ok' | 'on' | 'run' | 'wait' | 'stop' | 'off'

type Shape = 'tick' | 'dot' | 'clock' | 'cross' | 'ring'

/** The shape that says the state without its colour. A mark beside a name has no room for a tick, so a fine state is a dot there. */
const PILL_SHAPE: Record<StateTone, Shape> = { ok: 'tick', on: 'dot', run: 'dot', wait: 'clock', stop: 'cross', off: 'ring' }
const MARK_SHAPE: Record<StateTone, Shape> = { ...PILL_SHAPE, ok: 'dot' }

const round = { fill: 'none', stroke: 'currentColor', strokeLinecap: 'round', strokeLinejoin: 'round' } as const

/** The sketch's shapes, on a 12 px grid: the pill's at 12 px beside its word, the mark's bolder at 14 px on its own. */
const PILL_SHAPES: Record<Shape, ReactNode> = {
  tick: <path d="M2.2 6.4l2.4 2.4 5.2-5.4" {...round} strokeWidth={2} />,
  dot: <circle cx="6" cy="6" r="3.4" fill="currentColor" />,
  clock: (
    <>
      <circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" strokeWidth={1.6} />
      <path d="M6 3.6v2.6l1.7 1" {...round} strokeWidth={1.6} />
    </>
  ),
  cross: <path d="M3 3l6 6M9 3l-6 6" {...round} strokeWidth={2} />,
  ring: <circle cx="6" cy="6" r="3.6" fill="none" stroke="currentColor" strokeWidth={1.8} />,
}

const MARK_SHAPES: Record<Shape, ReactNode> = {
  ...PILL_SHAPES,
  dot: <circle cx="6" cy="6" r="5" fill="currentColor" />,
  clock: (
    <>
      <circle cx="6" cy="6" r="4.8" fill="none" stroke="currentColor" strokeWidth={1.8} />
      <path d="M6 3.4v2.8l1.8 1.1" {...round} strokeWidth={1.8} />
    </>
  ),
  cross: <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" {...round} strokeWidth={2.4} />,
  ring: <circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth={2} />,
}

interface StatePillProps extends HTMLAttributes<HTMLSpanElement> {
  readonly tone: StateTone
  readonly children: ReactNode
}

/** The one pill for every state: its shape and its word on a tint. */
export function StatePill({ tone, children, className, ...rest }: StatePillProps) {
  return (
    <span className={cx(styles['pill'], className)} {...rest} data-tone={tone}>
      <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false">
        {PILL_SHAPES[PILL_SHAPE[tone]]}
      </svg>
      {children}
    </span>
  )
}

/** A state as a shape alone, beside a name such as a workflow's. Its word is read out, and shows on hover. */
export function StateMark({ tone, word }: { readonly tone: StateTone; readonly word: string }) {
  return (
    <svg className={styles['mark']} data-tone={tone} viewBox="0 0 12 12" width="14" height="14" role="img" aria-label={word} focusable="false">
      <title>{word}</title>
      {MARK_SHAPES[MARK_SHAPE[tone]]}
    </svg>
  )
}
