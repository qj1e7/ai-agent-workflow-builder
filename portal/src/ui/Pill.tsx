import type { HTMLAttributes } from 'react'
import { cx } from './cx'
import styles from './Pill.module.css'

/** The words the app already uses for a state's colour, from every screen that drew its own pill. */
export type PillTone = 'on' | 'ok' | 'good' | 'run' | 'new' | 'open' | 'wait' | 'bad' | 'off' | 'quiet'

/** The sketch's six looks: a green dot, a green tick, a blue dot, an amber clock, a red cross and a grey ring. */
export type PillLook = 'on' | 'ok' | 'run' | 'wait' | 'err' | 'off'

const LOOK: Readonly<Record<PillTone, PillLook>> = { on: 'on', ok: 'ok', good: 'ok', run: 'run', new: 'run', open: 'run', wait: 'wait', bad: 'err', off: 'off', quiet: 'off' }

export function pillLook(tone: PillTone | undefined): PillLook {
  return tone ? LOOK[tone] : 'off'
}

interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  readonly tone?: PillTone | undefined
  /** In a page heading. */
  readonly large?: boolean
}

/**
 * The one pill: an icon and a word on a tint, never colour alone. The style draws the icon, so the pill holds its word and nothing else
 * and a screen reader reads that word once. It is the sketch's pill, `docs/design/chat-first/prototype.html`.
 */
export function Pill({ tone, large = false, className, children, ...rest }: PillProps) {
  return (
    <span className={cx(styles['pill'], styles[pillLook(tone)], large && styles['large'], className)} {...rest} data-tone={tone}>
      {children}
    </span>
  )
}
