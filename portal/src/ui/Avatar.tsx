import type { Actor } from '../api/types'
import { AgentFace } from './AgentFace'
import { GlyphPlatform, IconFlow, IconPerson } from './icons'
import { personTone } from './personTone'
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
    case 'agent':
      return <AgentFace id={props.agentId} size={size} />
    case 'person': {
      const { bg, ink } = personTone(props.name)
      return (
        <span
          className={cx(styles['avatar'], styles['person'])}
          style={{ ...box, background: bg, color: ink, fontSize: Math.max(12, Math.round(size * 0.4)) }}
          aria-hidden="true"
        >
          {props.name.trim().charAt(0).toUpperCase()}
        </span>
      )
    }
    case 'safety_checker':
      return (
        <span className={styles['avatar']} style={box} aria-hidden="true">
          <svg viewBox="0 0 24 24" width={size} height={size} focusable="false">
            <path d="M12 2l8.5 3v6.2c0 5.5-3.6 9.1-8.5 11-4.9-1.9-8.5-5.5-8.5-11V5z" fill="var(--ink)" />
            <path
              d="M8.2 12l2.7 2.7 5-5.2"
              fill="none"
              stroke="var(--surface)"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      )
    case 'empty_seat':
      return (
        <span className={cx(styles['avatar'], styles['seat'])} style={box} aria-hidden="true">
          <IconPerson size={Math.round(size * 0.42)} strokeWidth={2.2} />
        </span>
      )
  }
}

/** The face for whoever acted: an agent, a person, the safety checker, or a square mark for the workflow and the platform. */
export function ActorAvatar({ actor, size }: { actor: Actor; size: number }) {
  switch (actor.kind) {
    case 'agent':
      return <Avatar kind="agent" agentId={actor.id} size={size} />
    case 'user':
      return <Avatar kind="person" name={actor.display} size={size} />
    case 'safety_checker':
      return <Avatar kind="safety_checker" size={size} />
    case 'workflow':
      return (
        <span className={styles['system']} style={{ width: size, height: size }} aria-hidden="true">
          <IconFlow size={Math.round(size * 0.6)} />
        </span>
      )
    case 'platform':
      return (
        <span className={styles['system']} style={{ width: size, height: size }} aria-hidden="true">
          <GlyphPlatform size={Math.round(size * 0.6)} />
        </span>
      )
  }
}
