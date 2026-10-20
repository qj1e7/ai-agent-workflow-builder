import type { Actor } from '../api/types'
import type { RoomState } from '../run'
import { Avatar } from '../ui/Avatar'
import { GlyphPlatform, IconFlow, IconShield } from '../ui/icons'
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

/** The latest story event's summary, as the room's live region. */
export function Caption({ room }: { room: RoomState }) {
  const caption = room.caption
  return (
    <p className={styles['caption']} aria-live="polite" aria-atomic="true">
      {caption ? (
        <>
          <ActorAvatar actor={caption.actor} size={24} />
          <span>{caption.summary}</span>
        </>
      ) : (
        <>
          <IconShield size={18} />
          <span>Waiting for the run to start.</span>
        </>
      )}
    </p>
  )
}
