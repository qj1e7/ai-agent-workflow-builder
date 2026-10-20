import { useMemo, useRef } from 'react'
import type { ExpectedWrite, LiveView, Move, Point, RoomLayout, RoomState, SeatBox, SeatKey } from '../run'
import { agentSeatKey, layoutOf, stamps as stampsOf, stepSeatKey, ticketLife } from '../run'
import { Avatar } from '../ui/Avatar'
import { agentIdentity } from '../ui/agents'
import { cx } from '../ui/cx'
import { IconLock, IconPerson, IconUnlock, IconX } from '../ui/icons'
import { FloorPlan } from './FloorPlan'
import { useBeatAnimation, useReducedMotion } from './hooks'
import { EASE_MOVE, EASE_OVERSHOOT, POP, travelAlong } from './motion'
import { beatRoute, Paths } from './Paths'
import { Door, EmptySeatAvatar, Seat, SpeechCard, TicketCard, Token, type Travel } from './pieces'
import { agentStatus, approvedBy, checkerStatus, doorName, readDoorStatus, stepName, stepStatus, teamsStatus, ticketWords, writeDoorStatus } from './words'
import styles from './Room.module.css'

interface RoomProps {
  view: LiveView
  /** The measured width of the room's container. The page measures it, so it also knows when the room is compact. */
  width: number
  expectedWrites: readonly ExpectedWrite[]
  /** The stage's accessible label. The drawn room is aria-hidden; the sentence next to it says the state. */
  label: string
}

const LIGHT = { wide: 190, compact: 120 } as const

function beatOf(view: LiveView) {
  const beat = view.frame.beat
  return beat?.type === 'event' ? beat : null
}

function moveIs<T extends Move['type']>(move: Move | null, type: T): Extract<Move, { type: T }> | null {
  return move && move.type === type ? (move as Extract<Move, { type: T }>) : null
}

function seatTravel(key: string, from: Point, to: Point, durationMs: number, path: readonly Point[] | null): Travel {
  const keyframes = path && path.length >= 2 ? travelAlong(path, { fadeIn: true }) : [{ transform: `translate(${from.x - to.x}px, ${from.y - to.y}px)`, opacity: 0 }, { transform: 'translate(0, 0)', opacity: 1 }]
  return { key, keyframes, durationMs: Math.max(300, Math.round(durationMs * 0.8)), easing: EASE_MOVE }
}

export function Room({ view, width, expectedWrites, label }: RoomProps) {
  const reduced = useReducedMotion()
  const motion = !reduced
  const { room, frame } = view
  const layout = useMemo(() => (width > 0 ? view.layout(width, expectedWrites) : null), [view, width, expectedWrites])
  const beat = beatOf(view)
  const move = beat?.move ?? null
  const compact = layout?.size === 'compact'
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
  const openDoor = deliver ? deliver.door : null
  const approvers = approvedBy(room)
  const waited = frame.waiting?.elapsedMs ?? null

  if (!layout) {
    return <div className={styles['frame']} aria-label={label} role="img" />
  }

  const point = (anchor: Parameters<RoomLayout['point']>[0]) => layout.point(anchor)
  const lightPoint = room.light ? point(room.light.on) : null
  const lightSize = LIGHT[layout.size]
  const route = beatRoute(beat, room, layout)
  const beatPath = route ? layout.route(route.from, route.to) : null

  const lit = (key: SeatKey) => room.light !== null && seatKeyOfLight(room) === key

  const agentSeats = room.agents.map((seat) => {
    const key = agentSeatKey(seat.id)
    const box = layout.seats.get(key)
    if (!box) return null
    const identity = agentIdentity(seat.id, seat.display)
    const speaker = speak?.who
    const speaking = speaker?.at === 'agent' && speaker.id === seat.id
    const arriver = arrive?.who
    const arriving = arriver?.at === 'agent' && arriver.id === seat.id && beat
    const travel: Travel | null =
      arriving && beatPath ? seatTravel(beat.key, beatPath[0] as Point, point({ at: 'agent', id: seat.id }), beat.durationMs, beatPath) : null
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
        travel={travel}
        motion={motion}
        hue={identity.hue}
      />
    )
  })

  const leavingSeat = (() => {
    const who = leave?.who
    if (!leave || !beat || !who || who.at !== 'agent') return null
    const gone = beat.before.agents.find((seat) => seat.id === who.id)
    if (!gone) return null
    const beforeLayout = layoutOf(beat.before, width, expectedWrites)
    const box = beforeLayout.seats.get(agentSeatKey(gone.id)) ?? fallbackSeat(layout, point({ at: 'table' }))
    const host = room.agents.find((seat) => seat.role === 'host')
    const to = host ? point({ at: 'agent', id: host.id }) : point({ at: 'table' })
    const from = { x: box.avatar.x + box.avatar.w / 2, y: box.avatar.y + box.avatar.h / 2 }
    const travel: Travel = {
      key: beat.key,
      keyframes: [{ transform: 'translate(0, 0)', opacity: 1 }, { transform: `translate(${to.x - from.x}px, ${to.y - from.y}px)`, opacity: 0 }],
      durationMs: Math.round(beat.durationMs * 0.7),
    }
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
        travel={travel}
        motion={motion}
        hue={identity.hue}
        leaving
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
        travel={null}
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
    const deciding = decide?.step === step.index && beat
    const travel: Travel | null =
      deciding && beatPath ? seatTravel(beat.key, beatPath[0] as Point, point({ at: 'step', index: step.index }), beat.durationMs, beatPath) : null
    const name = stepName(step)
    return (
      <Seat
        key={key}
        kind={decided ? 'person' : 'empty'}
        seat={box}
        avatar={decided ? <Avatar kind="person" name={name} size={box.avatar.w} /> : <EmptySeatAvatar size={box.avatar.w} />}
        name={decided ? name : step.label}
        words={stepStatus(step, open ? waited : null)}
        breathing={open}
        lit={lit(key)}
        dimmed={false}
        travel={travel}
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
        travel={null}
        motion={motion}
      />
    )
  })

  const doors = layout.doors.map((door) => {
    const doorKey = door.key !== null && door.key !== 'teams' ? door.key : null
    const state = doorKey ? room.doors.find((d) => d.side !== 'teams' && d.key === doorKey) : null
    if (door.side === 'teams') {
      return <Door key="teams" door={door} name="Teams" words={teamsStatus(room.approval?.teams ?? null)} checker={null} stateIcon={IconPerson} />
    }
    if (door.side === 'read') {
      const words = doorKey ? readDoorStatus(room.trips, doorKey) : { text: 'Read only', tone: 'quiet' as const }
      return <Door key={`read:${doorKey ?? door.box.y}`} door={door} name={doorKey ? doorName({ side: 'read', key: doorKey }) : 'Reads'} words={words} checker={null} stateIcon={words.tone === 'fail' ? IconX : IconUnlock} />
    }
    const checker = state && state.side === 'write' ? state.checker : 'locked'
    const name = state && state.side === 'write' ? doorName(state) : doorName({ side: 'write', key: null, label: door.label })
    const written = room.ticket?.lines.some((line) => line.reference) ?? false
    const words = writeDoorStatus(checker, approvers, written)
    return (
      <Door
        key={`write:${door.key ?? door.label ?? door.box.y}`}
        door={door}
        name={name}
        words={words}
        checker={checkerStatus(checker)}
        stateIcon={checker === 'allowed' ? IconUnlock : checker === 'blocked' ? IconX : IconLock}
      />
    )
  })

  const ticket = (() => {
    if (!room.ticket || !life) return null
    const atEdge = room.phase.name === 'rejected'
    const box = atEdge ? layout.tableEdge : layout.ticketSpot
    const words = ticketWords(room.ticket, life)
    const rest = { x: box.x + box.w / 2, y: box.y + box.h / 2 }
    let travel: Travel | null = null
    if (beat && carry?.token === 'ticket' && beatPath) {
      travel = { key: beat.key, keyframes: travelAlong(beatPath, { fadeIn: carry.from.at === 'agent', tilt: -5 }), durationMs: beat.durationMs }
    } else if (beat && deliver) {
      const door = point({ at: 'door', key: deliver.door })
      const outside = { x: door.x + (door.x > rest.x ? 70 : -70), y: door.y }
      const dx = door.x - rest.x
      const dy = door.y - rest.y
      travel = {
        key: beat.key,
        keyframes: [
          { offset: 0, transform: 'translate(0, 0) scale(1)', opacity: 1 },
          { offset: 0.3, transform: `translate(${dx}px, ${dy}px) scale(0.6)`, opacity: 1 },
          { offset: 0.42, transform: `translate(${outside.x - rest.x}px, ${dy}px) scale(0.3)`, opacity: 0 },
          { offset: 0.58, transform: `translate(${outside.x - rest.x}px, ${dy}px) scale(0.3)`, opacity: 0 },
          { offset: 0.7, transform: `translate(${dx}px, ${dy}px) scale(0.6)`, opacity: 1 },
          { offset: 1, transform: 'translate(0, 0) scale(1)', opacity: 1 },
        ],
        durationMs: beat.durationMs,
        easing: EASE_MOVE,
      }
    }
    const stampKey = beat && decide ? beat.key : null
    return (
      <TicketCard
        box={box}
        ticket={room.ticket}
        life={life}
        words={words}
        stamps={stampList}
        travel={travel}
        stampKey={stampKey}
        motion={motion}
        compact={compact}
      />
    )
  })()

  const tokens = (() => {
    const out: React.ReactNode[] = []
    for (const trip of room.trips) {
      if (trip.state !== 'out') continue
      const at = point({ at: 'door', key: trip.door })
      const moving = beat && carry?.token === 'request' && carry.to.at === 'door' && carry.to.key === trip.door && carry.from.at === 'agent' && carry.from.id === trip.agent
      const travel = moving && beatPath ? { key: beat.key, keyframes: travelAlong(beatPath, { fadeIn: true }), durationMs: beat.durationMs } : null
      out.push(<Token key={`request:${trip.agent}:${trip.step}`} at={at} kind="request" label="Request" travel={travel} motion={motion} parked />)
    }
    if (beat && carry?.token === 'request' && carry.to.at === 'agent' && beatPath) {
      const frames = travelAlong(beatPath, {}).map((frame) => {
        const offset = typeof frame.offset === 'number' ? frame.offset : 0
        return offset > 0.75 ? { ...frame, opacity: 1 - (offset - 0.75) / 0.25 } : frame
      })
      frames.push({ offset: 1, transform: 'translate(0, 0)', opacity: 0 })
      out.push(<Token key={`answer:${beat.key}`} at={point(carry.to)} kind="request" label="Answer" travel={{ key: beat.key, keyframes: frames, durationMs: beat.durationMs }} motion={motion} parked={false} />)
    }
    if (beat && carry?.token === 'message' && beatPath) {
      const frames = travelAlong(beatPath, { fadeIn: true })
      frames.push({ offset: 1, transform: 'translate(0, 0)', opacity: 0 })
      out.push(<Token key={`message:${beat.key}`} at={point(carry.to)} kind="message" label="Approval request" travel={{ key: beat.key, keyframes: frames, durationMs: beat.durationMs }} motion={motion} parked={false} />)
    }
    return out
  })()

  const faultMark = (() => {
    if (!beat || !fault || fault.at.at === 'door') return null
    const at = point(fault.at)
    return <FaultBadge key={beat.key} beatKey={beat.key} at={at} motion={motion} />
  })()

  const speech = (() => {
    if (compact || !room.speech) return null
    const slot = layout.speech.get(agentSeatKey(room.speech.speaker))
    if (!slot) return null
    return <SpeechCard speech={room.speech} speakerName={agentIdentity(room.speech.speaker).name} card={slot.card} tailX={slot.tailX} variant="room" />
  })()

  const tableNote = !room.ticket ? (
    <p className={cx('plan-voice', styles['tableNote'])} style={{ left: layout.ticketSpot.x, top: layout.ticketSpot.y, width: layout.ticketSpot.w, height: layout.ticketSpot.h }}>
      {room.phase.name === 'failed' ? 'Nothing was proposed' : room.phase.name === 'succeeded' ? 'Nothing to write' : 'Proposed work lands here'}
    </p>
  ) : null

  return (
    <div className={styles['frame']}>
      <div className={cx(styles['stage'], dimmed && styles['stageDimmed'], styles[`stage_${layout.size}`])} style={{ height: layout.height }} aria-hidden="true">
        <div className={styles['reveal']} key={`reveal:${frame.take}`}>
          <FloorPlan layout={layout} openDoor={openDoor} />
        </div>
        {lightPoint ? (
          <div
            className={cx(styles['light'], styles[`light_${room.light?.tone ?? 'act'}`])}
            style={{ width: lightSize * 2, height: lightSize * 2, transform: `translate(${lightPoint.x - lightSize}px, ${lightPoint.y - lightSize}px)` }}
          />
        ) : null}
        <div className={styles['scrim']} style={{ left: layout.floor.x, top: layout.floor.y, width: layout.floor.w, height: layout.floor.h }} />
        <Paths layout={layout} room={room} beat={beat} motion={motion} />
        {tableNote}
        {doors}
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
      <p className="visually-hidden" role="img" aria-label={label}>
        {view.describe()}
      </p>
    </div>
  )
}

function FaultBadge({ at, beatKey, motion }: { at: Point; beatKey: string; motion: boolean }) {
  const ref = useRef<HTMLSpanElement>(null)
  useBeatAnimation(ref, beatKey, { keyframes: POP, options: { duration: 380, easing: EASE_OVERSHOOT, fill: 'both' } }, motion)
  return (
    <span ref={ref} className={styles['faultBadge']} style={{ left: at.x, top: at.y }}>
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

function fallbackSeat(layout: RoomLayout, at: Point): SeatBox {
  const size = layout.size === 'wide' ? 56 : 40
  return { box: { x: at.x - 64, y: at.y - size / 2, w: 128, h: 96 }, avatar: { x: at.x - size / 2, y: at.y - size / 2, w: size, h: size } }
}

