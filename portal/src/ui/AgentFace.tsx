import type { ReactNode } from 'react'
import { agentIdentity, type Accessory } from './agents'
import styles from './AgentFace.module.css'

/** Where the head sits in the 48 by 48 box. An accessory that hangs off one side moves the head away from it. */
const HEAD: Record<Accessory, readonly [number, number]> = {
  headset: [24, 26],
  magnifier: [22, 24],
  wrench: [22, 24],
  none: [24, 24],
}

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

interface AgentFaceProps {
  id: string
  size?: number
}

/** A round head in the agent's tint, two eyes, and one accessory in its hue. The name beside it is the text, so the face is hidden from screen readers. */
export function AgentFace({ id, size = 54 }: AgentFaceProps) {
  const { accessory, hue, tint } = agentIdentity(id)
  const [x, y] = HEAD[accessory]
  return (
    <svg className={styles['face']} viewBox="0 0 48 48" width={size} height={size} aria-hidden="true" focusable="false">
      <circle cx={x} cy={y} r="15" fill={tint} />
      <rect x={x - 7} y={y - 4} width="4" height="6.5" rx="2" fill="var(--face-ink)" />
      <rect x={x + 3} y={y - 4} width="4" height="6.5" rx="2" fill="var(--face-ink)" />
      {ACCESSORY[accessory](hue)}
    </svg>
  )
}
