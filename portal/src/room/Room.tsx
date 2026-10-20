import { useMemo, useRef, type ReactNode } from 'react'
import type { ExpectedWrite, Move, Point, RoomLayout, RoomState, RoomView, SeatKey } from '../run'
import { agentSeatKey, layoutOf, stamps as stampsOf, stepSeatKey, ticketLife } from '../run'
import { Avatar } from '../ui/Avatar'
import { agentIdentity } from '../ui/agents'
import { cx } from '../ui/cx'
import { IconLock, IconPerson, IconUnlock, IconX } from '../ui/icons'
import { CHIP_FOLD_LEAD_MS, CHIP_HOLD_MS, FindingChips } from './Finding'
import { FloorPlan } from './FloorPlan'
import { useBeatAnimation, useReducedMotion } from './hooks'
import { APPEAR_MS, EASE_OVERSHOOT, POP, TRAVEL_SHARE, travelAlong, walkAlong } from './motion'
import { beatRoute, beatWalk, Paths } from './Paths'
import { Door, EmptySeatAvatar, REST, Seat, SpeechCard, TicketCard, Token, type Appear, type Entrance, type TokenKind, type Travel, type Turn } from './pieces'
import { agentStatus, approvedBy, checkerStatus, doorName, readDoorStatus, stepName, stepStatus, teamsStatus, ticketWords, writeDoorAction, writeDoorStatus } from './words'
import styles from './Room.module.css'

interface RoomProps {
  view: RoomView
  /** The measured width of the room's container. The page measures it, so it also knows when the room is compact. */
  width: number
  expectedWrites: readonly ExpectedWrite[]
  /** The stage's accessible label. The drawn room is aria-hidden; the sentence next to it says the state. */
  label: string
  /** The overview's first load only: the plan rises, the doors follow, then the first beat. */
  opening?: boolean
}

const LIGHT = { wide: 260, compact: 140 } as const
const CUT_IN: Keyframe[] = [{ opacity: 0.35 }, { opacity: 1 }]

function beatOf(view: RoomView) {
  const beat = view.frame.beat
  return beat?.type === 'event' ? beat : null
}

function moveIs<T extends Move['type']>(move: Move | null, type: T): Extract<Move, { type: T }> | null {
  return move && move.type === type ? (move as Extract<Move, { type: T }>) : null
}

export function Room({ view, width, expectedWrites, label, opening = false }: RoomProps) {
  const reduced = useReducedMotion()
  const motion = !reduced
  const { room, frame } = view
  const layout = useMemo(() => (width > 0 ? view.layout(width, expectedWrites) : null), [view, width, expectedWrites])
  const beat = beatOf(view)
  const before = useMemo(() => (beat && width > 0 ? layoutOf(beat.before, width, expectedWrites) : null), [beat, width, expectedWrites])
  const contentsRef = useRef<HTMLDivElement>(null)
  useBeatAnimation(contentsRef, beat?.entry === 'cut' ? beat.key : null, { keyframes: CUT_IN, options: { duration: 180, fill: 'both' } }, motion)

  if (!layout) {
    return <div className={styles['frame']} aria-label={label} role="img" />
  }

  const move = beat?.move ?? null
  const compact = layout.size === 'compact'
  const dimmed = room.phase.name === 'awaiting_approval'
  const life = room.ticket ? ticketLife(room) : null
  const stampList = stampsOf(room)
  const speak = moveIs(move, 'speak')
  const deliver = moveIs(move, 'deliver')
  const carry = moveIs(move, 'carry')
  const arrive = moveIs(move, 'arrive')
  const leave = moveIs(move, 'leave')
  const decide = moveIs(move, 'decide')
  const fault = moveIs(move, 'fault')
  const approvers = approvedBy(room)
  const waited = frame.waiting?.elapsedMs ?? null
  const token = layout.token

  const point = (anchor: Parameters<RoomLayout['point']>[0]) => layout.point(anchor)
  const lightPoint = room.light ? point(room.light.on) : null
  const lightSize = LIGHT[layout.size]
  const route = beatRoute(beat, room, layout)
  const beatPath = route ? layout.route(route.from, route.to) : null
  const walk = beatWalk(beat, room, layout)
  const travelMs = beat ? Math.round(beat.durationMs * TRAVEL_SHARE) : 0
  const lit = (key: SeatKey) => room.light !== null && seatKeyOfLight(room) === key

  /** A seat or door that was not in the frame before this beat lands after the token that brought it, or at once. */
  const appearance = (fresh: boolean, afterTravel: boolean): Appear | null => {
    if (!beat || !fresh) return null
    return { key: beat.key, delayMs: afterTravel ? travelMs : 0 }
  }
  const entering = (fresh: boolean, afterTravel: boolean): Entrance => {
    const appear = appearance(fresh, afterTravel)
    return appear ? { kind: 'appear', ...appear } : REST
  }
  const walkingIn = (ghost: ReactNode | null): Entrance | null =>
    beat && walk ? { kind: 'walk', key: beat.key, keyframes: walkAlong(walk), durationMs: travelMs, ghost } : null
  const freshSeat = (key: SeatKey) => before !== null && !before.seats.has(key) && !before.overflow.some((o) => o.hidden.includes(key))
  const tokens: ReactNode[] = []
  const ride = (key: string, what: TokenKind, path: readonly Point[], o: { fadeIn?: boolean; fadeOut?: boolean; durationMs?: number; delayMs?: number; parked?: boolean }) => {
    if (!beat || path.length < 2) return
    const end = path[path.length - 1] as Point
    tokens.push(
      <Token
        key={key}
        at={end}
        size={token}
        what={what}
        travel={{ key: beat.key, keyframes: travelAlong(path, { fadeIn: o.fadeIn ?? false, fadeOut: o.fadeOut ?? false }), durationMs: o.durationMs ?? travelMs, delayMs: o.delayMs ?? 0 }}
        motion={motion}
        parked={o.parked ?? false}
      />,
    )
  }

  const agentSeats = room.agents.map((seat) => {
    const key = agentSeatKey(seat.id)
    const box = layout.seats.get(key)
    if (!box) return null
    const identity = agentIdentity(seat.id, seat.display)
    const speaker = speak?.who
    const speaking = speaker?.at === 'agent' && speaker.id === seat.id
    const arriving = arrive?.who.at === 'agent' && arrive.who.id === seat.id
    const walkIn = arriving ? walkingIn(null) : null
    if (arriving && beatPath && !walkIn) ride(`arrive:${seat.id}`, { kind: 'agent', agentId: seat.id }, beatPath, { fadeIn: true, fadeOut: true })
    return (
      <Seat
        key={key}
        kind="agent"
        seat={box}
        avatar={<Avatar kind="agent" agentId={seat.id} size={box.avatar.w} />}
        name={identity.name}
        words={agentStatus(seat, speaking)}
        breathing={speaking || seat.status === 'working'}
        lit={lit(key)}
        dimmed={dimmed}
        entrance={walkIn ?? entering(freshSeat(key), arriving && beatPath !== null)}
        motion={motion}
        hue={identity.hue}
      />
    )
  })

  const leavingSeat = (() => {
    const who = leave?.who
    if (!leave || !beat || !who || who.at !== 'agent' || !before) return null
    const gone = beat.before.agents.find((seat) => seat.id === who.id)
    const box = before.seats.get(agentSeatKey(who.id))
    if (!gone || !box) return null
    if (beatPath) ride(`leave:${gone.id}`, { kind: 'agent', agentId: gone.id }, beatPath, { fadeIn: true, fadeOut: true, durationMs: beat.durationMs })
    const identity = agentIdentity(gone.id, gone.display)
    return (
      <Seat
        key={`leaving:${gone.id}`}
        kind="agent"
        seat={box}
        avatar={<Avatar kind="agent" agentId={gone.id} size={box.avatar.w} />}
        name={identity.name}
        words={{ text: 'Leaving', tone: 'quiet' }}
        breathing={false}
        lit={false}
        dimmed={false}
        entrance={{ kind: 'fade', key: beat.key, durationMs: Math.round(beat.durationMs * 0.3) }}
        motion={motion}
        hue={identity.hue}
      />
    )
  })()

  const starterSeat = (() => {
    if (!room.starter) return null
    const box = layout.seats.get('starter')
    if (!box) return null
    return (
      <Seat
        key="starter"
        kind="person"
        seat={box}
        avatar={<Avatar kind="person" name={room.starter.display} size={box.avatar.w} />}
        name={room.starter.display}
        words={{ text: 'Operator', tone: 'quiet' }}
        statusIcon={IconPerson}
        breathing={false}
        lit={lit('starter')}
        dimmed={false}
        entrance={entering(freshSeat('starter'), false)}
        motion={motion}
      />
    )
  })()

  const stepSeats = (room.approval?.steps ?? []).map((step) => {
    const key = stepSeatKey(step.index)
    const box = layout.seats.get(key)
    if (!box) return null
    const decided = step.state.is === 'approved' || step.state.is === 'declined'
    const open = step.state.is === 'open'
    const deciding = decide?.step === step.index && beat !== null
    const name = stepName(step)
    const walkIn = deciding ? walkingIn(<EmptySeatAvatar size={box.avatar.w} />) : null
    if (deciding && beatPath && !walkIn) {
      const teams = layout.doors.find((door) => door.side === 'teams')
      ride(`decide:${step.index}`, { kind: 'person', name }, teams ? [teams.outside, ...beatPath] : beatPath, { fadeOut: true })
    }
    return (
      <Seat
        key={key}
        kind={decided ? 'person' : 'empty'}
        seat={box}
        avatar={decided ? <Avatar kind="person" name={name} size={box.avatar.w} /> : <EmptySeatAvatar size={box.avatar.w} />}
        name={decided ? name : step.label}
        words={stepStatus(step, open && waited !== null ? { ms: waited, spedUp: frame.spedUp, compact } : null)}
        {...(step.state.is === 'declined' ? { statusIcon: IconX } : {})}
        breathing={open}
        lit={lit(key)}
        dimmed={false}
        entrance={walkIn ?? entering(freshSeat(key) || deciding, deciding && beatPath !== null)}
        motion={motion}
      />
    )
  })

  const overflowSeats = layout.overflow.map((seat) => {
    const names = seat.hidden.map((key) => nameOfSeat(room, key)).filter((name): name is string => name !== null)
    const hiddenOpen = seat.row === 'people' && (room.approval?.steps ?? []).some((step) => step.state.is === 'open' && seat.hidden.includes(stepSeatKey(step.index)))
    return (
      <Seat
        key={`overflow:${seat.row}`}
        kind="overflow"
        seat={seat.seat}
        avatar={<span className={styles['overflowAvatar']} style={{ width: seat.seat.avatar.w, height: seat.seat.avatar.h }}>+{seat.hidden.length}</span>}
        name={`${seat.hidden.length} more`}
        words={hiddenOpen && waited !== null ? { text: `Waiting ${Math.floor(waited / 60000)} min`, tone: 'wait' } : { text: names.slice(0, 2).join(', '), tone: 'quiet' }}
        breathing={hiddenOpen}
        lit={false}
        dimmed={false}
        entrance={REST}
        motion={motion}
      />
    )
  })

  const doorOrder = [...layout.doors].sort((a, b) => (a.side === b.side ? a.box.y - b.box.y : sideRank[a.side] - sideRank[b.side]))
  const doors = layout.doors.map((door) => {
    const doorKey = door.key !== null && door.key !== 'teams' ? door.key : null
    const state = doorKey ? room.doors.find((d) => d.side !== 'teams' && d.key === doorKey) : null
    const fresh = before !== null && !before.doors.some((d) => d.side === door.side && d.key === door.key && d.label === door.label)
    const appear = appearance(fresh, false)
    const order = doorOrder.indexOf(door)
    const name = doorName(door)
    if (door.side === 'teams') {
      return <Door key="teams" door={door} name={name} action={null} words={teamsStatus(room.approval?.teams ?? null)} checker={null} stateIcon={IconPerson} appear={appear} motion={motion} order={order} />
    }
    if (door.side === 'read') {
      const words = doorKey ? readDoorStatus(room.trips, doorKey) : { text: 'Read only', tone: 'quiet' as const }
      return (
        <Door
          key={`read:${doorKey ?? door.box.y}`}
          door={door}
          name={name}
          action={null}
          words={words}
          checker={null}
          stateIcon={words.tone === 'fail' ? IconX : IconUnlock}
          appear={appear}
          motion={motion}
          order={order}
        />
      )
    }
    const checker = state && state.side === 'write' ? state.checker : 'locked'
    const written = room.ticket?.lines.some((line) => line.reference) ?? false
    return (
      <Door
        key={`write:${door.key ?? door.label ?? door.box.y}`}
        door={door}
        name={name}
        action={writeDoorAction(door, room.ticket)}
        words={writeDoorStatus(checker, approvers, written)}
        checker={checkerStatus(checker)}
        stateIcon={checker === 'allowed' ? IconUnlock : checker === 'blocked' ? IconX : IconLock}
        appear={appear}
        motion={motion}
        order={order}
      />
    )
  })

  const ticket = (() => {
    if (!room.ticket || !life) return null
    const atEdge = room.phase.name === 'rejected'
    const box = atEdge ? layout.tableEdge : layout.ticketSpot
    const words = ticketWords(room.ticket, life)
    let travel: Travel | null = null
    let appear: Appear | null = null
    let turn: Turn | null = null
    if (beat && carry?.token === 'ticket' && beatPath) {
      if (carry.from.at === 'table' && carry.to.at === 'table_edge') {
        travel = { key: beat.key, keyframes: travelAlong(beatPath), durationMs: beat.durationMs }
      } else {
        ride('ticket', { kind: 'ticket' }, beatPath, { fadeIn: true, fadeOut: true })
        appear = { key: beat.key, delayMs: travelMs }
      }
    } else if (beat && deliver && beatPath) {
      const door = layout.doors.find((candidate) => candidate.key === deliver.door) ?? layout.doors.find((candidate) => candidate.hidden.includes(deliver.door))
      const out = door ? [...beatPath, door.outside] : beatPath
      const legMs = Math.round(beat.durationMs * 0.4)
      ride('ticket:out', { kind: 'ticket' }, out, { durationMs: legMs, fadeIn: true })
      ride('ticket:back', { kind: 'key' }, [...out].reverse(), { durationMs: legMs, delayMs: Math.round(beat.durationMs * 0.55), fadeOut: true })
      const previous = beat.before.ticket ? ticketLife(beat.before) : null
      if (previous && beat.before.ticket) turn = { key: beat.key, atMs: Math.round(beat.durationMs * 0.9), before: ticketWords(beat.before.ticket, previous) }
    } else if (beat && !beat.before.ticket) {
      appear = { key: beat.key, delayMs: 0 }
    }
    return (
      <TicketCard
        box={box}
        ticket={room.ticket}
        life={life}
        words={words}
        stamps={stampList}
        travel={travel}
        appear={appear}
        turn={turn}
        stampKey={beat && decide ? beat.key : null}
        stampDelayMs={travelMs + APPEAR_MS}
        motion={motion}
        compact={compact}
      />
    )
  })()

  for (const trip of room.trips) {
    if (trip.state !== 'out') continue
    const at = point({ at: 'door', key: trip.door })
    const moving = beat && carry?.token === 'request' && carry.to.at === 'door' && carry.to.key === trip.door && carry.from.at === 'agent' && carry.from.id === trip.agent
    if (moving && beatPath) {
      ride(`request:${trip.agent}:${trip.step}`, { kind: 'request' }, beatPath, { fadeIn: true, durationMs: beat.durationMs, parked: true })
    } else {
      tokens.push(<Token key={`request:${trip.agent}:${trip.step}`} at={at} size={token} what={{ kind: 'request' }} travel={null} motion={motion} parked />)
    }
  }
  if (beat && carry?.token === 'request' && carry.to.at === 'agent' && beatPath) {
    ride(`answer:${beat.key}`, { kind: 'request' }, beatPath, { fadeOut: true, durationMs: beat.durationMs })
  }
  if (beat && carry?.token === 'message' && beatPath) {
    const teams = layout.doors.find((door) => door.side === 'teams')
    ride(`message:${beat.key}`, { kind: 'message' }, teams ? [...beatPath, teams.outside] : beatPath, { fadeIn: true, durationMs: beat.durationMs })
  }

  const faultMark = (() => {
    if (!beat || !fault || fault.at.at === 'door') return null
    return <FaultBadge key={beat.key} beatKey={beat.key} at={point(fault.at)} motion={motion} />
  })()

  const speech = (() => {
    if (!room.speech) return null
    const slot = layout.speech.get(agentSeatKey(room.speech.speaker))
    if (!slot) return null
    return <SpeechCard speech={room.speech} speakerName={agentIdentity(room.speech.speaker).name} card={slot.card} tailX={slot.tailX} />
  })()

  const finding = (() => {
    const spot = layout.ticketSpot
    if (room.finding && !room.ticket) {
      const land =
        beat && beat.before.finding !== room.finding
          ? { key: beat.key, fromMs: travelMs, byMs: beat.durationMs - CHIP_HOLD_MS, agentAt: point({ at: 'agent', id: room.finding.agent }) }
          : null
      return <FindingChips finding={room.finding} spot={spot} size={layout.size} land={land} fold={null} motion={motion} />
    }
    const folded = beat && carry?.token === 'ticket' && carry.to.at === 'table' ? beat.before.finding : null
    if (!beat || !folded || !motion) return null
    return <FindingChips finding={folded} spot={spot} size={layout.size} land={null} fold={{ key: beat.key, atMs: Math.max(0, travelMs - CHIP_FOLD_LEAD_MS) }} motion={motion} />
  })()

  const tableNote = !room.ticket && !room.finding ? (
    <p className={cx('plan-voice', styles['tableNote'])} style={{ left: layout.ticketSpot.x, top: layout.ticketSpot.y, width: layout.ticketSpot.w, height: layout.ticketSpot.h }}>
      <span data-room-label="table">{room.phase.name === 'failed' ? 'Nothing was proposed' : room.phase.name === 'succeeded' ? 'Nothing to write' : 'Proposed work lands here'}</span>
    </p>
  ) : null

  return (
    <div className={styles['frame']}>
      <div
        className={cx(styles['stage'], dimmed && styles['stageDimmed'], styles[`stage_${layout.size}`], opening && motion && styles['stageOpening'])}
        style={{ height: layout.height, '--token': `${token}px` } as React.CSSProperties}
        aria-hidden="true"
        data-stage={layout.size}
      >
        <FloorPlan layout={layout} openDoor={deliver ? deliver.door : null} order={doorOrder} />
        {lightPoint ? (
          <div
            className={cx(styles['light'], styles[`light_${room.light?.tone ?? 'act'}`])}
            style={{ width: lightSize * 2, height: lightSize * 2, transform: `translate(${lightPoint.x - lightSize}px, ${lightPoint.y - lightSize}px)` }}
          />
        ) : null}
        <div className={styles['scrim']} style={{ left: layout.floor.x, top: layout.floor.y, width: layout.floor.w, height: layout.floor.h }} />
        <div className={styles['doors']}>{doors}</div>
        <div ref={contentsRef} className={styles['contents']}>
          <Paths layout={layout} room={room} beat={beat} motion={motion} />
          {tableNote}
          {finding}
          {ticket}
          {agentSeats}
          {leavingSeat}
          {starterSeat}
          {stepSeats}
          {overflowSeats}
          {tokens}
          {faultMark}
          {speech}
        </div>
      </div>
      <p className="visually-hidden" role="img" aria-label={label}>
        {view.describe()}
      </p>
    </div>
  )
}

const sideRank = { read: 0, write: 1, teams: 2 } as const

function FaultBadge({ at, beatKey, motion }: { at: Point; beatKey: string; motion: boolean }) {
  const ref = useRef<HTMLSpanElement>(null)
  useBeatAnimation(ref, beatKey, { keyframes: POP, options: { duration: 380, easing: EASE_OVERSHOOT, fill: 'both' } }, motion)
  return (
    <span ref={ref} className={styles['faultBadge']} style={{ left: at.x - 13, top: at.y - 13 }}>
      <IconX size={14} strokeWidth={2.5} />
    </span>
  )
}

function seatKeyOfLight(room: RoomState): SeatKey | null {
  const on = room.light?.on
  if (!on) return null
  switch (on.at) {
    case 'agent':
      return agentSeatKey(on.id)
    case 'starter':
      return 'starter'
    case 'step':
      return stepSeatKey(on.index)
    default:
      return null
  }
}

function nameOfSeat(room: RoomState, key: SeatKey): string | null {
  if (key === 'starter') return room.starter?.display ?? null
  if (key.startsWith('step:')) {
    const step = room.approval?.steps.find((candidate) => stepSeatKey(candidate.index) === key)
    return step ? stepName(step) : null
  }
  const seat = room.agents.find((candidate) => agentSeatKey(candidate.id) === key)
  return seat ? agentIdentity(seat.id, seat.display).name : null
}
