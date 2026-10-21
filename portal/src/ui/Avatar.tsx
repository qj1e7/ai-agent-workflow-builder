import { agentIdentity } from './agents'
import { IconPerson } from './icons'
import { cx } from './cx'
import styles from './Avatar.module.css'

type AvatarVariant =
  | { kind: 'agent'; agentId: string }
  | { kind: 'person'; name: string }
  | { kind: 'safety_checker' }
  | { kind: 'empty_seat' }

export type AvatarProps = AvatarVariant & { size?: number }

export function Avatar(props: AvatarProps) {
  const size = props.size ?? 40
  const box = { width: size, height: size }

  switch (props.kind) {
    case 'agent': {
      const { glyph: Glyph, hue } = agentIdentity(props.agentId)
      return (
        <span className={cx(styles['avatar'], styles['agent'])} style={{ ...box, background: hue }} aria-hidden="true">
          <Glyph size={Math.round(size * 0.6)} strokeWidth={1.75} />
        </span>
      )
    }
    case 'person':
      return (
        <span
          className={cx(styles['avatar'], styles['person'])}
          style={{ ...box, fontSize: Math.max(12, Math.round(size * 0.42)) }}
          aria-hidden="true"
        >
          {props.name.trim().charAt(0).toUpperCase()}
        </span>
      )
    case 'safety_checker':
      return (
        <span className={styles['avatar']} style={box} aria-hidden="true">
          <svg viewBox="0 0 24 24" width={size} height={size} focusable="false">
            <path
              d="M12 2.6l8.2 2.9v6.3c0 4.6-3.3 8.3-8.2 9.9-4.9-1.6-8.2-5.3-8.2-9.9V5.5z"
              fill="var(--safety)"
            />
            <path
              d="M8.4 12.1l2.5 2.5 4.7-5"
              fill="none"
              stroke="var(--surface)"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      )
    case 'empty_seat':
      return (
        <span className={cx(styles['avatar'], styles['seat'])} style={box} aria-hidden="true">
          <IconPerson size={Math.round(size * 0.5)} />
        </span>
      )
  }
}
