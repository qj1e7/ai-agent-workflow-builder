import { useState, type ReactNode } from 'react'
import { agentIdentity, type Accessory } from './agents'
import styles from './AgentFace.module.css'

/** What the agent is doing, always from the real state of the work. The words beside the face say the same. */
export type FaceState = 'idle' | 'thinking' | 'working' | 'waiting' | 'success' | 'error' | 'stopped'

/** Where the head sits in the 48 by 48 box. An accessory that hangs off one side moves the head away from it. */
const HEAD: Record<Accessory, readonly [number, number]> = {
  headset: [24, 26],
  magnifier: [22, 24],
  wrench: [22, 24],
  none: [24, 24],
}

const INK = 'var(--face-ink)'

const ACCESSORY: Record<Accessory, (hue: string) => ReactNode> = {
  headset: (hue) => (
    <>
      <path d="M7.5 25a16.5 16.5 0 0 1 33 0" fill="none" stroke={hue} strokeWidth="3.2" strokeLinecap="round" />
      <rect x="4.5" y="21" width="6.5" height="11" rx="3.2" fill={hue} />
      <rect x="37" y="21" width="6.5" height="11" rx="3.2" fill={hue} />
      <path d="M40 31.5c0 6-4 8.5-9.5 8.5" fill="none" stroke={hue} strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="30" cy="40" r="2.8" fill={hue} />
    </>
  ),
  magnifier: (hue) => (
    <>
      <circle cx="34.5" cy="33.5" r="7" fill="var(--face-lens)" stroke={hue} strokeWidth="3.2" />
      <path d="M39.6 38.6l5 5" stroke={hue} strokeWidth="4.2" strokeLinecap="round" />
    </>
  ),
  wrench: (hue) => (
    <g transform="rotate(-45 36 36)" fill={hue}>
      <rect x="33.6" y="33" width="4.8" height="15" rx="2.4" />
      <path d="M30 31.5a6 6 0 1 1 12 0v1.2h-3.3v-4.4h-5.4v4.4H30z" />
    </g>
  ),
  none: () => null,
}

function Eyes({ x, y, state }: { x: number; y: number; state: FaceState }) {
  const [top, height] = state === 'stopped' ? [0.5, 1.8] : state === 'waiting' ? [-5, 5.5] : [-4, 6.5]
  const eye = (dx: number) => <rect x={x + dx} y={y + top} width="4" height={height} rx={Math.min(2, height / 2)} fill={INK} />
  return (
    <g className={styles['eyes']}>
      {eye(-7)}
      {eye(3)}
    </g>
  )
}

function Badge({ fill, className, children }: { fill: string; className: string | undefined; children: ReactNode }) {
  return (
    <g className={className}>
      <circle cx="40" cy="9" r="7.5" fill="var(--surface)" />
      <circle cx="40" cy="9" r="6" fill={fill} />
      {children}
    </g>
  )
}

interface AgentFaceProps {
  id: string
  display?: string
  size?: number
  state?: FaceState
}

/**
 * A round head in the agent's tint, two eyes, and one accessory in its hue, in one of seven states. Only the
 * agent working now loops; a change of state after the face first appears reacts once. The name beside it is
 * the text, so the face is hidden from screen readers.
 */
export function AgentFace({ id, display, size = 54, state = 'idle' }: AgentFaceProps) {
  const { accessory, hue, tint } = agentIdentity(id, display)
  const [x, y] = HEAD[accessory]
  const [firstState] = useState(state)
  return (
    <svg
      className={styles['face']}
      data-state={state}
      data-accessory={accessory}
      data-react={state !== firstState || undefined}
      viewBox="0 0 48 48"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <g className={styles['body']}>
        <circle cx={x} cy={y} r="15" fill={tint} />
        {state === 'error' ? (
          <path d={`M${x - 8} ${y - 6.5}l4.5-2.2M${x + 8} ${y - 6.5}l-4.5-2.2`} stroke={INK} strokeWidth="1.8" strokeLinecap="round" fill="none" />
        ) : null}
        <Eyes x={x} y={y} state={state} />
        {state === 'success' ? (
          <path
            className={styles['happy']}
            d={`M${x - 7} ${y + 0.5}q2-3.2 4 0M${x + 3} ${y + 0.5}q2-3.2 4 0`}
            stroke={INK}
            strokeWidth="2"
            strokeLinecap="round"
            fill="none"
          />
        ) : null}
        <g className={styles['accessory']}>{ACCESSORY[accessory](hue)}</g>
        {state === 'working' && accessory === 'none' ? (
          <g className={styles['typing']} fill={hue}>
            <rect x={x - 6} y="42" width="3" height="4" rx="1" />
            <rect x={x - 1.5} y="42" width="3" height="4" rx="1" />
            <rect x={x + 3} y="42" width="3" height="4" rx="1" />
          </g>
        ) : null}
      </g>
      {state === 'thinking' ? (
        <g className={styles['think']}>
          <circle cx="36.5" cy="6.5" r="1.3" />
          <circle cx="40.5" cy="4" r="1.7" />
          <circle cx="45" cy="2" r="2.1" />
        </g>
      ) : null}
      {state === 'waiting' ? (
        <Badge fill="var(--amber)" className={styles['badge']}>
          <path d="M40 5.6v3.6l2.2 1.3" stroke={INK} strokeWidth="1.6" strokeLinecap="round" fill="none" />
        </Badge>
      ) : null}
      {state === 'error' ? (
        <Badge fill="var(--red)" className={styles['badge']}>
          <path d="M40 5.4v4.2M40 12.3v.2" stroke="var(--on-status)" strokeWidth="1.9" strokeLinecap="round" />
        </Badge>
      ) : null}
      {state === 'success' ? (
        <Badge fill="var(--green)" className={styles['ok']}>
          <path d="M37.3 9.2l1.9 1.9 3.6-3.8" stroke="var(--on-status)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </Badge>
      ) : null}
    </svg>
  )
}
