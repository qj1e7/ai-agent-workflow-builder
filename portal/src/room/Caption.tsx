import type { Actor } from '../api/types'
import { Avatar } from '../ui/Avatar'
import { GlyphPlatform, IconFlow } from '../ui/icons'
import styles from './Caption.module.css'

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
        <span className={styles['systemAvatar']} style={{ width: size, height: size }} aria-hidden="true">
          <IconFlow size={Math.round(size * 0.6)} />
        </span>
      )
    case 'platform':
      return (
        <span className={styles['systemAvatar']} style={{ width: size, height: size }} aria-hidden="true">
          <GlyphPlatform size={Math.round(size * 0.6)} />
        </span>
      )
  }
}
