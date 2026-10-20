import { useRef, type ReactNode } from 'react'
import type { Box, DoorBox, Point, SeatBox, Speech, Stamp, Ticket, TicketLife } from '../run'
import { Avatar } from '../ui/Avatar'
import { agentIdentity } from '../ui/agents'
import { cx } from '../ui/cx'
import {
  IconAlert,
  IconArrow,
  IconCheck,
  IconChat,
  IconClock,
  IconLock,
  IconRepo,
  IconRing,
  IconTicket,
  IconUnlock,
  IconWave,
  IconX,
  type Icon,
} from '../ui/icons'
import { useBeatAnimation, type AnimationPlan } from './hooks'
import { EASE_MOVE, EASE_OVERSHOOT, STAMP } from './motion'
import type { StatusWords, TicketWords } from './words'
import styles from './Room.module.css'

const toneIcon: Record<StatusWords['tone'], Icon> = {
  quiet: IconRing,
  live: IconWave,
  wait: IconClock,
  done: IconCheck,
  fail: IconAlert,
}

export function StatusLine({ words, icon }: { words: StatusWords; icon?: Icon }) {
  const Mark = icon ?? toneIcon[words.tone]
  return (
    <span className={cx(styles['status'], styles[`tone_${words.tone}`])}>
      <Mark size={12} />
      <span>{words.text}</span>
    </span>
  )
}

export interface Travel {
  readonly key: string
  readonly keyframes: Keyframe[]
  readonly durationMs: number
  readonly easing?: string
  readonly delayMs?: number
}

function planOf(travel: Travel | null): AnimationPlan | null {
  if (!travel) return null
  return {
    keyframes: travel.keyframes,
    options: { duration: travel.durationMs, easing: travel.easing ?? EASE_MOVE, delay: travel.delayMs ?? 0, fill: 'both' },
  }
}

export function placeAt(box: Box): { left: number; top: number; width: number; height: number } {
  return { left: box.x, top: box.y, width: box.w, height: box.h }
}

interface SeatProps {
  seat: SeatBox
  avatar: ReactNode
  name: string
  words: StatusWords
  statusIcon?: Icon
  breathing: boolean
  lit: boolean
  dimmed: boolean
  travel: Travel | null
  motion: boolean
  kind: 'agent' | 'person' | 'empty' | 'overflow'
  hue?: string
  leaving?: boolean
}

export function Seat({ seat, avatar, name, words, statusIcon, breathing, lit, dimmed, travel, motion, kind, hue, leaving }: SeatProps) {
  const ref = useRef<HTMLDivElement>(null)
  useBeatAnimation(ref, travel?.key ?? null, planOf(travel), motion)
  return (
    <div
      ref={ref}
      className={cx(styles['seat'], styles[`seat_${kind}`], breathing && styles['breathing'], lit && styles['lit'], dimmed && styles['dimmed'], leaving && styles['leaving'])}
      style={{ ...placeAt(seat.box), '--hue': hue } as React.CSSProperties}
    >
      <span className={styles['avatarWrap']} style={{ width: seat.avatar.w, height: seat.avatar.h }}>
        {avatar}
        <span className={styles['ring']} aria-hidden="true" />
        <span className={styles['dimmer']} aria-hidden="true" />
      </span>
      <span className={styles['name']}>{name}</span>
      <StatusLine words={words} {...(statusIcon ? { icon: statusIcon } : {})} />
    </div>
  )
}

interface DoorProps {
  door: DoorBox
  name: string
  words: StatusWords
  checker: StatusWords | null
  stateIcon: Icon
}

const sideIcon: Record<DoorBox['side'], Icon> = { read: IconRepo, write: IconTicket, teams: IconChat }

export function Door({ door, name, words, checker, stateIcon: State }: DoorProps) {
  const Side = sideIcon[door.side]
  const right = door.side === 'write'
  return (
    <div className={cx(styles['door'], styles[`door_${door.side}`])} style={placeAt(door.box)}>
      <div className={cx(styles['doorLabel'], right && styles['doorLabelRight'])} style={{ height: door.labelBox.h }}>
        <span className={styles['doorName']}>
          {right ? null : <Side size={14} />}
          {name}
          {right ? <Side size={14} /> : null}
        </span>
        <span className={cx(styles['doorState'], styles[`tone_${words.tone}`])}>
          <State size={11} />
          {words.text}
        </span>
      </div>
      {checker && door.checker ? (
        <div className={styles['checker']} style={{ left: door.checker.x - door.box.x, top: door.checker.y - door.box.y, width: door.checker.w, height: door.checker.h }}>
          <Avatar kind="safety_checker" size={28} />
          <span className={styles['checkerName']}>Safety checker</span>
          <span className={cx(styles['checkerState'], styles[`tone_${checker.tone}`])}>
            {checker.tone === 'done' ? <IconUnlock size={11} /> : checker.tone === 'fail' ? <IconX size={11} /> : <IconLock size={11} />}
            {checker.text}
          </span>
        </div>
      ) : null}
    </div>
  )
}

interface TicketCardProps {
  box: Box
  ticket: Ticket
  life: TicketLife
  words: TicketWords
  stamps: readonly Stamp[]
  travel: Travel | null
  stampKey: string | null
  motion: boolean
  compact: boolean
}

export function TicketCard({ box, ticket, life, words, stamps, travel, stampKey, motion, compact }: TicketCardProps) {
  const ref = useRef<HTMLDivElement>(null)
  const stampRef = useRef<HTMLSpanElement>(null)
  useBeatAnimation(ref, travel?.key ?? null, planOf(travel), motion)
  useBeatAnimation(stampRef, stampKey, { keyframes: STAMP, options: { duration: 320, easing: EASE_OVERSHOOT, delay: 900, fill: 'backwards' } }, motion)
  const Mark = words.tone === 'done' ? IconCheck : words.tone === 'fail' ? IconX : words.tone === 'wait' ? IconClock : IconLock
  const last = stamps[stamps.length - 1]
  const line = ticket.lines[0]
  return (
    <div ref={ref} className={cx(styles['ticket'], styles[`ticket_${life}`], compact && styles['ticketCompact'])} style={placeAt(box)}>
      <div className={styles['ticketHead']}>
        <span className={styles['ticketTag']}>{words.tag}</span>
        <span className={cx(styles['ticketState'], styles[`tone_${words.tone}`])}>
          <Mark size={12} />
          {words.line}
        </span>
      </div>
      <p className={styles['ticketLine']}>{line?.line ?? 'A write action'}</p>
      {ticket.lines.length > 1 ? <p className={styles['ticketMore']}>and {ticket.lines.length - 1} more</p> : null}
      {last ? (
        <span ref={stampRef} className={cx(styles['stamp'], last.verdict === 'approve' ? styles['stampApproved'] : styles['stampDeclined'])}>
          {last.verdict === 'approve' ? <IconCheck size={12} /> : <IconX size={12} />}
          {last.verdict === 'approve' ? 'Approved' : 'Declined'}, {last.by.display}
        </span>
      ) : null}
    </div>
  )
}

interface TokenProps {
  at: Point
  kind: 'request' | 'message'
  label: string
  travel: Travel | null
  motion: boolean
  parked: boolean
}

export function Token({ at, kind, label, travel, motion, parked }: TokenProps) {
  const ref = useRef<HTMLDivElement>(null)
  useBeatAnimation(ref, travel?.key ?? null, planOf(travel), motion)
  const Mark = kind === 'request' ? IconRepo : IconChat
  return (
    <div ref={ref} className={cx(styles['token'], styles[`token_${kind}`], parked && styles['tokenParked'])} style={{ left: at.x, top: at.y }}>
      <Mark size={12} />
      {label}
    </div>
  )
}

interface SpeechCardProps {
  speech: Speech
  speakerName: string
  card?: Box
  tailX?: number
  variant: 'room' | 'slot'
}

export function SpeechCard({ speech, speakerName, card, tailX, variant }: SpeechCardProps) {
  const identity = agentIdentity(speech.speaker)
  const to = speech.to.kind === 'agent' ? speech.to.display : 'Everyone'
  const style = card ? ({ ...placeAt(card), '--hue': identity.hue, '--tail': `${(tailX ?? card.x + card.w / 2) - card.x}px` } as React.CSSProperties) : ({ '--hue': identity.hue } as React.CSSProperties)
  return (
    <div key={speech.seq} className={cx(styles['speech'], variant === 'slot' ? styles['speechSlot'] : styles['speechRoom'])} style={style}>
      <div className={styles['speechHead']}>
        <Avatar kind="agent" agentId={speech.speaker} size={20} />
        <span className={styles['speechWho']}>{speakerName}</span>
        <IconArrow size={12} />
        <span className={styles['speechTo']}>{to}</span>
      </div>
      <p className={styles['speechText']}>{speech.text}</p>
      {variant === 'room' ? <span className={styles['speechTail']} aria-hidden="true" /> : null}
    </div>
  )
}

export function EmptySeatAvatar({ size }: { size: number }) {
  return <Avatar kind="empty_seat" size={size} />
}
