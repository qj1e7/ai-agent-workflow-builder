import { useId, type CSSProperties } from 'react'
import styles from './PlannerBot.module.css'

export type BotState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'sorry'

const GLOW = 'color-mix(in srgb, var(--lead) 45%, #ffffff)'

function Features({ state }: { state: BotState }) {
  const eyes =
    state === 'sorry' ? (
      <path d="M17 24.5L22 22.9M31 22.9L26 24.5" stroke={GLOW} strokeWidth="2.9" strokeLinecap="round" fill="none" />
    ) : (
      <>
        <rect x="14.9" y="19.2" width="4.2" height="6.6" rx="2.1" fill={GLOW} />
        <rect x="28.9" y="19.2" width="4.2" height="6.6" rx="2.1" fill={GLOW} />
      </>
    )
  const mouth =
    state === 'speaking' ? (
      <g className={styles['wave']}>
        {[-4, -2, 0, 2, 4].map((dx) => (
          <rect key={dx} x={24 + dx - 0.7} y="26.9" width="1.4" height="4" rx="0.7" fill={GLOW} />
        ))}
      </g>
    ) : state === 'thinking' ? (
      <g className={styles['think']}>
        {[-3.5, 0, 3.5].map((dx) => (
          <circle key={dx} cx={24 + dx} cy="28.8" r="1.2" fill={GLOW} />
        ))}
      </g>
    ) : state === 'sorry' ? (
      <path d="M21.4 29.6q2.6-1.8 5.2 0" stroke={GLOW} strokeWidth="1.7" strokeLinecap="round" fill="none" />
    ) : null
  return (
    <>
      <g className={styles['eyes']}>{eyes}</g>
      {mouth}
    </>
  )
}

interface PlannerBotProps {
  readonly state?: BotState
  readonly size?: number
  /** Counts keystrokes, so each one lights the ears once while someone types. */
  readonly keys?: number
  /** How far the eyes lean toward the caret, from -1 to 1. */
  readonly look?: number
}

/**
 * The Planner as the Visor bot: a white egg with a dark visor, glowing eyes and two ear lights. The face is for the
 * eye only. The words beside it say the same thing, so it is hidden from screen readers.
 */
export function PlannerBot({ state = 'idle', size = 128, keys = 0, look = 0 }: PlannerBotProps) {
  const id = useId()
  const body = `${id}b`
  const visor = `${id}v`
  const ear = `${id}e`
  return (
    <svg
      className={styles['bot']}
      data-state={state}
      viewBox="0 0 48 48"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      style={{ '--lx': `${(look * 1.4).toFixed(2)}px` } as CSSProperties}
    >
      <defs>
        <radialGradient id={body} cx="40%" cy="30%" r="75%">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.65" stopColor="color-mix(in srgb, var(--lead) 8%, #ffffff)" />
          <stop offset="1" stopColor="color-mix(in srgb, var(--lead) 28%, #ffffff)" />
        </radialGradient>
        <linearGradient id={visor} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1d2a44" />
          <stop offset="1" stopColor="#070c16" />
        </linearGradient>
        <radialGradient id={ear} cx="40%" cy="35%" r="70%">
          <stop offset="0" stopColor="color-mix(in srgb, var(--lead) 40%, #ffffff)" />
          <stop offset="1" stopColor="color-mix(in srgb, var(--lead) 85%, #0b1020)" />
        </radialGradient>
      </defs>
      <ellipse cx="24" cy="45" rx="12" ry="2.2" fill="#0f1420" opacity="0.14" />
      <g className={styles['body']}>
        <circle key={`l${String(keys)}`} className={keys > 0 ? styles['ping'] : undefined} cx="8.6" cy="25" r="3.6" fill={`url(#${ear})`} />
        <circle key={`r${String(keys)}`} className={keys > 0 ? styles['ping'] : undefined} cx="39.4" cy="25" r="3.6" fill={`url(#${ear})`} />
        <path d="M24 5C33 5 39.5 13 39.5 23.5C39.5 34.5 33 42 24 42C15 42 8.5 34.5 8.5 23.5C8.5 13 15 5 24 5Z" fill={`url(#${body})`} />
        <path d="M12.5 19C12.5 15 17.5 13 24 13C30.5 13 35.5 15 35.5 19V25.5C35.5 30 30.5 32.5 24 32.5C17.5 32.5 12.5 30 12.5 25.5Z" fill={`url(#${visor})`} />
        <path d="M15 17C17 15.2 20.5 14.6 23.5 14.6" stroke="#ffffff" strokeOpacity="0.35" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        <Features state={state} />
        <path d="M18 37.5c3.5 1.6 8.5 1.6 12 0" stroke="color-mix(in srgb, var(--lead) 35%, #ffffff)" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.7" />
      </g>
    </svg>
  )
}
