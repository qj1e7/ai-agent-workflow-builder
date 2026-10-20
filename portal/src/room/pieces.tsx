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
import { APPEAR, APPEAR_MS, EASE_MOVE, EASE_OVERSHOOT, FADE_OUT, STAMP } from './motion'
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

/** A piece that fades and scales into place during a beat, after the token that brought it has landed. */
export interface Appear {
  readonly key: string
  readonly delayMs: number
}

function planOf(travel: Travel | null): AnimationPlan | null {
  if (!travel) return null
  return {
    keyframes: travel.keyframes,
    options: { duration: travel.durationMs, easing: travel.easing ?? EASE_MOVE, delay: travel.delayMs ?? 0, fill: 'both' },
  }
}

function appearPlan(appear: Appear | null): AnimationPlan | null {
  if (!appear) return null
  return { keyframes: APPEAR, options: { duration: APPEAR_MS, easing: EASE_MOVE, delay: appear.delayMs, fill: 'both' } }
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
  appear: Appear | null
  /** The seat fades out in place while a token carries its agent away. */
  fade: Travel | null
  motion: boolean
  kind: 'agent' | 'person' | 'empty' | 'overflow'
  hue?: string
}

export function Seat({ seat, avatar, name, words, statusIcon, breathing, lit, dimmed, appear, fade, motion, kind, hue }: SeatProps) {
  const ref = useRef<HTMLDivElement>(null)
  useBeatAnimation(ref, fade?.key ?? appear?.key ?? null, fade ? planOf(fade) : appearPlan(appear), motion)
  return (
    <div
      ref={ref}
      className={cx(styles['seat'], styles[`seat_${kind}`], breathing && styles['breathing'], lit && styles['lit'], dimmed && styles['dimmed'])}
      style={{ ...placeAt(seat.box), '--hue': hue } as React.CSSProperties}
    >
      <span className={styles['avatarWrap']} style={{ width: seat.avatar.w, height: seat.avatar.h }}>
        {avatar}
        <span className={styles['ring']} aria-hidden="true" />
        <span className={styles['dimmer']} aria-hidden="true" />
      </span>
      <span className={styles['labels']} style={{ maxWidth: seat.label.w }} data-room-label="seat">
        <span className={styles['name']}>{name}</span>
        <StatusLine words={words} {...(statusIcon ? { icon: statusIcon } : {})} />
      </span>
    </div>
  )
}

interface DoorProps {
  door: DoorBox
  name: string
  words: StatusWords
  checker: StatusWords | null
  stateIcon: Icon
  appear: Appear | null
  motion: boolean
  /** Position in the opening's left-to-right stagger. */
  order: number
}

const sideIcon: Record<DoorBox['side'], Icon> = { read: IconRepo, write: IconTicket, teams: IconChat }

export function Door({ door, name, words, checker, stateIcon: State, appear, motion, order }: DoorProps) {
  const ref = useRef<HTMLDivElement>(null)
  useBeatAnimation(ref, appear?.key ?? null, appearPlan(appear), motion)
  const Side = sideIcon[door.side]
  const right = door.side === 'write'
  return (
    <div ref={ref} className={cx(styles['door'], styles[`door_${door.side}`])} style={{ ...placeAt(door.box), '--i': order } as React.CSSProperties}>
      <div className={cx(styles['doorLabel'], right && styles['doorLabelRight'])} style={{ height: door.labelBox.h, width: door.labelBox.w }} data-room-label="door">
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
        <div
          className={styles['checker']}
          style={{ left: door.checker.x - door.box.x, top: door.checker.y - door.box.y, width: door.checker.w, height: door.checker.h }}
          data-room-label="checker"
        >
          <span className={styles['checkerWords']}>
            <span className={styles['checkerName']}>Safety checker</span>
            <span className={cx(styles['checkerState'], styles[`tone_${checker.tone}`])}>
              {checker.tone === 'done' ? <IconUnlock size={11} /> : checker.tone === 'fail' ? <IconX size={11} /> : <IconLock size={11} />}
              {checker.text}
            </span>
          </span>
          <Avatar kind="safety_checker" size={door.checker.h} />
        </div>
      ) : null}
    </div>
  )
}

/** The head of the ticket turns from the words before a beat to the words after it, once the token is back. */
export interface Turn {
  readonly key: string
  readonly atMs: number
  readonly before: TicketWords
}

interface TicketCardProps {
  box: Box
  ticket: Ticket
  life: TicketLife
  words: TicketWords
  stamps: readonly Stamp[]
  /** The rejected ticket's slide to the table's edge: the one move the card itself makes, and it stays inside the table. */
  travel: Travel | null
  appear: Appear | null
  turn: Turn | null
  stampKey: string | null
  stampDelayMs: number
  motion: boolean
  compact: boolean
}

function TicketHead({ words, compact }: { words: TicketWords; compact: boolean }) {
  const Mark = words.tone === 'done' ? IconCheck : words.tone === 'fail' ? IconX : words.tone === 'wait' ? IconClock : IconLock
  return (
    <>
      {compact ? null : <span className={styles['ticketTag']}>{words.tag}</span>}
      <span className={cx(styles['ticketState'], styles[`tone_${words.tone}`])}>
        <Mark size={12} />
        {compact ? (
          <>
            {words.short}
            {words.reference ? (
              <>
                {' '}
                <span className={styles['ticketKey']}>{words.reference}</span>
              </>
            ) : null}
          </>
        ) : (
          words.line
        )}
      </span>
    </>
  )
}

export function TicketCard({ box, ticket, life, words, stamps, travel, appear, turn, stampKey, stampDelayMs, motion, compact }: TicketCardProps) {
  const ref = useRef<HTMLDivElement>(null)
  const stampRef = useRef<HTMLSpanElement>(null)
  const beforeRef = useRef<HTMLDivElement>(null)
  const afterRef = useRef<HTMLDivElement>(null)
  useBeatAnimation(ref, travel?.key ?? appear?.key ?? null, travel ? planOf(travel) : appearPlan(appear), motion)
  useBeatAnimation(stampRef, stampKey, { keyframes: STAMP, options: { duration: 320, easing: EASE_OVERSHOOT, delay: stampDelayMs, fill: 'backwards' } }, motion)
  useBeatAnimation(beforeRef, turn?.key ?? null, turn ? { keyframes: FADE_OUT, options: { duration: 180, delay: turn.atMs, fill: 'both' } } : null, motion)
  useBeatAnimation(afterRef, turn?.key ?? null, turn ? { keyframes: APPEAR, options: { duration: 180, delay: turn.atMs, fill: 'both' } } : null, motion)
  const last = stamps[stamps.length - 1]
  const line = ticket.lines[0]
  return (
    <div ref={ref} className={cx(styles['ticket'], styles[`ticket_${life}`], compact && styles['ticketCompact'])} style={placeAt(box)} data-ticket={life}>
      <div className={styles['ticketHeadRow']}>
        <div ref={afterRef} className={styles['ticketHead']}>
          <TicketHead words={words} compact={compact} />
        </div>
        {turn && motion ? (
          <div ref={beforeRef} className={cx(styles['ticketHead'], styles['ticketHeadBefore'])}>
            <TicketHead words={turn.before} compact={compact} />
          </div>
        ) : null}
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

export type TokenKind =
  | { readonly kind: 'request' }
  | { readonly kind: 'message' }
  | { readonly kind: 'ticket' }
  | { readonly kind: 'key' }
  | { readonly kind: 'agent'; readonly agentId: string }
  | { readonly kind: 'person'; readonly name: string }

interface TokenProps {
  at: Point
  size: number
  what: TokenKind
  travel: Travel | null
  motion: boolean
  parked: boolean
}

/** The only thing that travels: a chip no wider than the layout's token, centred on its point. */
export function Token({ at, size, what, travel, motion, parked }: TokenProps) {
  const ref = useRef<HTMLDivElement>(null)
  useBeatAnimation(ref, travel?.key ?? null, planOf(travel), motion)
  const style = { left: at.x - size / 2, top: at.y - size / 2, width: size, height: size }
  const inner = (() => {
    switch (what.kind) {
      case 'request':
        return <IconRepo size={Math.round(size * 0.55)} />
      case 'message':
        return <IconChat size={Math.round(size * 0.55)} />
      case 'ticket':
        return <IconTicket size={Math.round(size * 0.55)} />
      case 'key':
        return <IconCheck size={Math.round(size * 0.6)} strokeWidth={2.25} />
      case 'agent':
        return <Avatar kind="agent" agentId={what.agentId} size={size} />
      case 'person':
        return <Avatar kind="person" name={what.name} size={size} />
    }
  })()
  return (
    <div ref={ref} className={cx(styles['token'], styles[`token_${what.kind}`], parked && styles['tokenParked'])} style={style} data-travel={what.kind}>
      {inner}
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
    <div key={speech.seq} className={cx(styles['speech'], variant === 'slot' ? styles['speechSlot'] : styles['speechRoom'])} style={style} data-speech={speech.seq}>
      <div className={styles['speechHead']}>
        <Avatar kind="agent" agentId={speech.speaker} size={18} />
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
