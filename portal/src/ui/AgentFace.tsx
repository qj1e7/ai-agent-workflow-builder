import { useId, useState, type ReactNode } from 'react'
import { agentIdentity, type Job } from './agents'
import { PlannerBot, type BotState } from './PlannerBot'
import styles from './AgentFace.module.css'

export type FaceState = 'idle' | 'thinking' | 'working' | 'waiting' | 'success' | 'error' | 'stopped'

const PLANNER_ID = 'planner'
const INK = 'var(--face-ink)'

/** An Orb shows its job badge from this size up. Below it the badge would be a smudge. */
export const JOB_BADGE_MIN_SIZE = 32

const BOT_STATE: Record<FaceState, BotState> = {
  idle: 'idle',
  thinking: 'thinking',
  working: 'thinking',
  waiting: 'idle',
  success: 'idle',
  error: 'sorry',
  stopped: 'idle',
}

const GLYPH: Record<Job, ReactNode> = {
  magnifier: (
    <>
      <circle cx="38.7" cy="38.7" r="2.4" fill="none" stroke="#fff" strokeWidth="1.5" />
      <path d="M40.5 40.5l2 2" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
    </>
  ),
  wrench: <path d="M42.6 36.4a2.6 2.6 0 0 1-3.1 3.3l-2.9 2.9-1.4-1.4 2.9-2.9a2.6 2.6 0 0 1 3.3-3.1l-1.5 1.5 1.2 1.2z" fill="#fff" />,
}

function Eyes({ state }: { state: FaceState }) {
  const rect = (x: number, y: number, height: number) => (
    <rect x={x - 2} y={y - height / 2} width="4" height={height} rx={Math.min(2, height / 2)} fill={INK} />
  )
  const [left, right] = [19, 29]
  const eyes =
    state === 'stopped' ? (
      <>
        {rect(left, 26.5, 1.8)}
        {rect(right, 26.5, 1.8)}
      </>
    ) : state === 'waiting' ? (
      <>
        {rect(left, 23, 5.5)}
        {rect(right, 23, 5.5)}
      </>
    ) : (
      <>
        {rect(left, 25, 6.5)}
        {rect(right, 25, 6.5)}
      </>
    )
  return (
    <>
      {state === 'error' ? (
        <path d="M15.5 19.6l4.5-2M32.5 19.6l-4.5-2" stroke={INK} strokeWidth="1.8" strokeLinecap="round" fill="none" />
      ) : null}
      <g className={styles['eyes']}>{eyes}</g>
      {state === 'success' ? (
        <path
          className={styles['happy']}
          d="M17 26q2-3.4 4 0M27 26q2-3.4 4 0"
          stroke={INK}
          strokeWidth="2.2"
          strokeLinecap="round"
          fill="none"
        />
      ) : null}
    </>
  )
}

function Ring({ fill, className, children }: { fill: string; className: string | undefined; children: ReactNode }) {
  return (
    <g className={className}>
      <circle cx="40" cy="9" r="7.5" fill="var(--surface)" />
      <circle cx="40" cy="9" r="6" fill={fill} />
      {children}
    </g>
  )
}

/** The status badge, top right on a ring, shared by the Orb and the Visor bot. It says the same as the words beside the face. */
function StatusBadge({ state }: { state: FaceState }) {
  if (state === 'waiting') {
    return (
      <Ring fill="var(--amber)" className={styles['badge']}>
        <path d="M40 5.6v3.6l2.2 1.3" stroke={INK} strokeWidth="1.6" strokeLinecap="round" fill="none" />
      </Ring>
    )
  }
  if (state === 'error') {
    return (
      <Ring fill="var(--red)" className={styles['badge']}>
        <path d="M40 5.4v4.2M40 12.3v.2" stroke="var(--on-status)" strokeWidth="1.9" strokeLinecap="round" />
      </Ring>
    )
  }
  if (state === 'success') {
    return (
      <Ring fill="var(--green)" className={styles['ok']}>
        <path d="M37.3 9.2l1.9 1.9 3.6-3.8" stroke="var(--on-status)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </Ring>
    )
  }
  return null
}

interface AgentFaceProps {
  id: string
  display?: string
  size?: number
  state?: FaceState
}

/**
 * Every agent has a face. The Planner is the Visor bot and every other agent is a flat Orb in its own colour, with a
 * badge for its job from 32 px up. The state comes from the real state of the work. The name beside the face is the
 * text, so the face is hidden from screen readers.
 */
export function AgentFace({ id, display, size = 54, state = 'idle' }: AgentFaceProps) {
  const { hue, tint, job } = agentIdentity(id, display)
  const gradient = useId()
  const [firstState] = useState(state)
  const react = state !== firstState || undefined

  if (id === PLANNER_ID) {
    return (
      <span className={styles['planner']} data-face="visor" data-state={state} data-react={react} style={{ width: size, height: size }} aria-hidden="true">
        <PlannerBot state={BOT_STATE[state]} size={size} still />
        <svg className={styles['overlay']} viewBox="0 0 48 48" width={size} height={size} focusable="false">
          <StatusBadge state={state} />
        </svg>
      </span>
    )
  }

  const showJob = job !== undefined && size >= JOB_BADGE_MIN_SIZE
  return (
    <svg
      className={styles['face']}
      data-face="orb"
      data-state={state}
      data-react={react}
      data-job={showJob ? job : undefined}
      viewBox="0 0 48 48"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id={gradient} cx="40%" cy="34%" r="72%">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.5" stopColor={tint} />
          <stop offset="1" stopColor={hue} />
        </radialGradient>
      </defs>
      <g className={styles['body']}>
        <circle cx="24" cy="25" r="21" fill={hue} opacity="0.12" />
        <circle cx="24" cy="25" r="17" fill={`url(#${gradient})`} />
        <g className={styles['spin']}>
          <ellipse cx="15.5" cy="16.5" rx="4.6" ry="2.4" fill="#fff" opacity="0.8" transform="rotate(-38 15.5 16.5)" />
        </g>
        <Eyes state={state} />
      </g>
      {state === 'thinking' ? (
        <g className={styles['think']}>
          <circle cx="36.5" cy="6.5" r="1.3" />
          <circle cx="40.5" cy="4" r="1.7" />
          <circle cx="45" cy="2" r="2.1" />
        </g>
      ) : null}
      {showJob ? (
        <g>
          <circle cx="39.5" cy="39.5" r="7.2" fill="var(--surface)" />
          <circle cx="39.5" cy="39.5" r="5.9" fill={hue} />
          {GLYPH[job]}
        </g>
      ) : null}
      <StatusBadge state={state} />
    </svg>
  )
}
