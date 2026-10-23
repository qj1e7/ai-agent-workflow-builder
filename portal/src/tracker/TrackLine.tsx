import { useEffect, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { displayName, usePeople, type Person } from '../api/people'
import {
  captionWords,
  castLayout,
  figureWords,
  moreWords,
  parcelShortWords,
  parcelWords,
  SPED_UP_WORDS,
  stopWords,
  type AgentStatus,
  type BeatPlan,
  type Figure,
  type Gate,
  type Items,
  type Parcel,
  type ParcelForm,
  type Speech,
  type Stop,
  type StopKind,
  type Track,
} from '../run'
import { AgentFace } from '../ui/AgentFace'
import { agentIdentity } from '../ui/agents'
import { Avatar } from '../ui/Avatar'
import { cx } from '../ui/cx'
import { IconBox, IconCheck, IconDash, IconDoc, IconLock, IconPause, IconPerson, IconSpinner, IconX } from '../ui/icons'
import { personTone } from '../ui/personTone'
import { createMotion, type Motion } from './motion'
import { captionKey, followLayout, layoutKey, place, type Follow } from './place'
import styles from './TrackLine.module.css'

export interface TrackLineProps {
  readonly track: Track
  /** The playing beat. Omit for a line that never moves, such as the first screen. */
  readonly plan?: BeatPlan | null
  /** Drawn under track.panel's stop. */
  readonly panel?: ReactNode
  readonly reduced?: boolean
  /** Nothing will move or open: the first screen. The line drops the room it keeps for speech and panels. */
  readonly still?: boolean
  readonly label?: string
}

/**
 * Draws the shown frame's final state from the Track alone. After each commit, place() hangs the parcel, the fill,
 * the break and the slots off the measured nodes, and the motion plays the beat's acts into that state. A Track with
 * no plan is simply correct.
 */
export function TrackLine({ track, plan = null, panel = null, reduced = false, still = false, label = 'Where the work is' }: TrackLineProps) {
  const route = useRef<HTMLElement>(null)
  const motion = useRef<Motion | null>(null)
  const follow = useRef<Follow | null>(null)
  const placedFor = useRef<string | null>(null)
  const scene = { track, plan, reduced }
  const latest = useRef(scene)
  const users = usePeople()

  // A replay hold renders every 50 ms to move one counter, so the line is measured again only when a part could move.
  useLayoutEffect(() => {
    latest.current = scene
    const element = route.current
    const key = `${layoutKey(track)}|${plan?.key ?? ''}|${users ? 'named' : ''}`
    if (!element || key === placedFor.current) return
    placedFor.current = key
    motion.current ??= createMotion()
    motion.current.update(element, scene, place(element, track))
    follow.current?.rescan()
  })

  useEffect(() => {
    const element = route.current
    if (!element) return
    follow.current = followLayout(element, () => {
      const now = latest.current
      motion.current?.update(element, now, place(element, now.track))
    })
    return () => {
      follow.current?.stop()
      follow.current = null
      placedFor.current = null
      motion.current?.reset()
    }
  }, [])

  return (
    <section ref={route} className={cx(styles['route'], track.cut && styles['cut'], still && styles['still'])} aria-label={label}>
      <div className={styles['rail']} aria-hidden="true" />
      <div className={styles['fill']} aria-hidden="true" />
      {track.breakAt === null ? null : <BreakMark />}
      <ol className={styles['stops']}>
        {track.stops.map((stop, index) => (
          <StopItem
            key={stop.key}
            stop={stop}
            parcel={track.parcel?.at === index ? track.parcel.form : null}
            gate={track.gate?.stop === index ? track.gate : null}
            speech={track.speech?.stop === index ? track.speech : null}
            panel={track.panel?.stop === index ? panel : null}
            holds={!still && HOLDS.has(stop.kind)}
            captions={!still && stop.kind !== 'done' && stop.kind !== 'draft'}
            users={users}
          />
        ))}
      </ol>
      {track.parcel ? <ParcelMark parcel={track.parcel} /> : null}
      <div className={styles['ghosts']} aria-hidden="true" />
    </section>
  )
}

/** Stops someone can stand over. On the phone they keep a cast row from the start, so an arrival never pushes the line down. */
const HOLDS: ReadonlySet<StopKind> = new Set(['start', 'agent', 'draft', 'gate'])

interface StopItemProps {
  readonly stop: Stop
  readonly parcel: ParcelForm | null
  readonly gate: Gate | null
  readonly speech: Speech | null
  readonly panel: ReactNode
  readonly holds: boolean
  /** Every stop but Done and Draft keeps the caption row on the phone, so words that come and go never move the stops below. Draft's only caption, "Not needed", comes at the very end of a run with nothing to write. */
  readonly captions: boolean
  readonly users: readonly Person[] | undefined
}

function StopItem({ stop, parcel, gate, speech, panel, holds, captions, users }: StopItemProps) {
  return (
    <li
      className={cx(
        styles['stop'],
        (stop.state === 'future' || stop.state === 'not_needed') && styles['future'],
        holds && styles['holds'],
        captions && styles['captions'],
      )}
      data-stop={stop.key}
      data-state={stop.state}
      data-gate={gate?.state}
      aria-current={stop.state === 'current' ? 'step' : undefined}
    >
      <div className={styles['text']}>
        <span className={styles['label']}>{stop.name}</span>
        <span className={styles['cap']} aria-hidden="true">
          {stop.caption.is === 'none' ? null : (
            <span key={captionKey(stop.caption)} className={styles['capIn']}>
              <Caption stop={stop} />
            </span>
          )}
        </span>
        <span className="visually-hidden">{stopWords(stop, parcel)}</span>
      </div>
      <Cast figures={stop.cast} users={users} />
      <div className={styles['nodeRow']} aria-hidden="true">
        {gate ? <GateMark gate={gate} /> : null}
        <span data-node className={cx(styles['node'], stop.state === 'not_needed' && styles['dashed'])}>
          <NodeFill stop={stop} gate={gate} />
        </span>
      </div>
      {speech ? (
        <div className={styles['slotAbove']}>
          <Bubble speech={speech} />
        </div>
      ) : null}
      {panel ? <div className={styles['slotBelow']}>{panel}</div> : null}
    </li>
  )
}

/** Keyed by state, so a change mounts a new fill the motion can pop in at the node's act. */
function NodeFill({ stop, gate }: { stop: Stop; gate: Gate | null }) {
  switch (stop.state) {
    case 'passed':
      return <Fill key="passed" tone="passed" />
    case 'current':
      return gate ? null : <Fill key="passed" tone="passed" />
    case 'failed':
      return <Fill key="failed" tone="failed" />
    case 'done':
      return <Fill key="done" tone="done" />
    default:
      return null
  }
}

function Fill({ tone }: { tone: 'passed' | 'failed' | 'done' }) {
  return <span className={cx(styles['nodeFill'], styles[tone])}>{tone === 'failed' ? <IconX strokeWidth={2.6} /> : <IconCheck strokeWidth={2.6} />}</span>
}

function Caption({ stop }: { stop: Stop }) {
  const caption = stop.caption
  switch (caption.is) {
    case 'found':
      return <Chips items={caption.items} />
    case 'waiting':
      return (
        <>
          <span className={cx(styles['state'], styles['wait'])}>
            <IconPause strokeWidth={2.2} />
            <span className={styles['clock']}>{captionWords(caption)}</span>
          </span>
          {caption.spedUp ? <span className={styles['tag']}>{SPED_UP_WORDS}</span> : null}
        </>
      )
    case 'approved':
      return <StateWords tone="ok" words={captionWords(caption)} />
    case 'declined':
    case 'stopped':
      return <StateWords tone="bad" words={captionWords(caption)} />
    case 'write':
      if (caption.status === 'written') return <StateWords tone="ok" words={captionWords(caption)} />
      if (caption.status === 'blocked') return <StateWords tone="bad" words={captionWords(caption)} />
      return captionWords(caption)
    default:
      return captionWords(caption) || null
  }
}

function StateWords({ tone, words }: { tone: 'ok' | 'bad'; words: string }) {
  return (
    <span className={cx(styles['state'], styles[tone])}>
      {tone === 'ok' ? <IconCheck strokeWidth={2.2} /> : <IconX strokeWidth={2.2} />}
      {words}
    </span>
  )
}

function Chips({ items }: { items: Items }) {
  if (items.is === 'count') return <span className={styles['chip']}>{parcelWords({ is: 'found', items })}</span>
  return (
    <>
      {items.items.map((item) => (
        <span key={item} className={styles['chip']}>
          {item}
        </span>
      ))}
    </>
  )
}

export function Cast({ figures, users }: { figures: readonly Figure[]; users: readonly Person[] | undefined }) {
  const layout = castLayout(figures.length)
  const compact = layout.size === 'compact'
  return (
    <div className={cx(styles['cast'], compact && styles['compact'])}>
      {figures.slice(0, layout.shown).map((figure) => (
        <FigureMark key={figure.key} figure={figure} users={users} badge={compact} />
      ))}
      {layout.more > 0 ? (
        <div className={styles['who']}>
          <span className={cx(styles['av'], styles['more'])} aria-hidden="true">
            +{layout.more}
          </span>
          <span className="visually-hidden">{moreWords(figures.slice(layout.shown))}</span>
        </div>
      ) : null}
    </div>
  )
}

function statusOf(figure: Figure): string {
  switch (figure.is) {
    case 'agent':
      return figure.status
    case 'person':
      return figure.verdict === null ? 'started' : figure.verdict === 'approve' ? 'approved' : 'declined'
    case 'seat':
      return figure.open ? 'open' : 'locked'
  }
}

function FigureMark({ figure, users, badge }: { figure: Figure; users: readonly Person[] | undefined; badge: boolean }) {
  const named = figure.is === 'person' && users ? { ...figure, name: displayName(users, figure.id) } : figure
  const name = named.is === 'seat' ? named.label : named.name
  const acting = named.is !== 'seat' && named.acting
  const ring = named.is === 'agent' ? agentIdentity(named.id).hue : 'var(--ink)'
  return (
    <div
      className={cx(styles['who'], acting && styles['acting'])}
      data-figure={named.key}
      data-status={statusOf(named)}
      style={{ '--ring': ring } as CSSProperties}
    >
      <span className={styles['av']}>
        <Face figure={named} name={name} />
        {badge && named.is === 'agent' && named.status !== 'present' ? <StatusBadge status={named.status} /> : null}
      </span>
      <span className={styles['nm']} aria-hidden="true">
        {name}
      </span>
      <span className="visually-hidden">{figureWords(named)}</span>
    </div>
  )
}

/** On a crowded stop, which agent works, is done or stopped, by its icon as well as its colour. The figure's words say it too. */
function StatusBadge({ status }: { status: Exclude<AgentStatus, 'present'> }) {
  return (
    <span className={cx(styles['badge'], styles[`badge_${status}`])}>
      {status === 'stopped' ? <IconX strokeWidth={3} /> : status === 'done' ? <IconCheck strokeWidth={3} /> : <IconSpinner strokeWidth={3} />}
    </span>
  )
}

function Face({ figure, name }: { figure: Figure; name: string }) {
  switch (figure.is) {
    case 'agent':
      return <AgentFace id={figure.id} size={54} />
    case 'person': {
      const tone = personTone(name)
      return (
        <span className={styles['person']} style={{ background: tone.bg, color: tone.ink }}>
          {name.trim().charAt(0).toUpperCase()}
        </span>
      )
    }
    case 'seat':
      return <span className={cx(styles['seat'], !figure.open && styles['locked'])}>{figure.open ? <IconPerson strokeWidth={2.2} /> : <IconLock strokeWidth={2.2} />}</span>
  }
}

/** The boom barrier: the safety checker's shield on the line and a striped arm, keyed by state so its colours can crossfade. */
function GateMark({ gate }: { gate: Gate }) {
  return (
    <>
      <span className={styles['housing']}>
        <span className={styles['ringGhost']} />
        <span key={gate.state} className={cx(styles['ring'], styles[`ring_${gate.state}`])} />
        <Avatar kind="safety_checker" size={28} />
      </span>
      <span className={cx(styles['arm'], gate.state === 'open' && styles['open'])}>
        <span className={styles['armGhost']} />
        <span key={gate.state} className={cx(styles['stripes'], styles[`stripes_${gate.state}`])} />
      </span>
    </>
  )
}

function BreakMark() {
  return (
    <div className={styles['break']} aria-hidden="true">
      <svg viewBox="0 0 30 46" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" focusable="false">
        <path d="M4 23h3l3-8 3 16 3-8" />
        <path d="M26 23h-3" />
        <path d="M8 6l4 4M8 40l4-4M22 6l-3 4M22 40l-3-4" />
      </svg>
    </div>
  )
}

function Bubble({ speech }: { speech: Speech }) {
  return (
    <div className={styles['bubble']} style={{ '--who': agentIdentity(speech.speaker).hue } as CSSProperties}>
      <span className={styles['by']}>{speech.name}</span>
      <p>{speech.text}</p>
    </div>
  )
}

/** The one moving thing. Its body is keyed by form, so the motion can fade the old body out while the new one swaps in. */
function ParcelMark({ parcel }: { parcel: Parcel }) {
  const form = parcel.form
  return (
    <div className={styles['parcel']} data-parcel={form.is} aria-hidden="true">
      <div className={styles['shaker']}>
        <span className={styles['parcelGhost']} />
        <ParcelBody key={JSON.stringify(form)} form={form} />
      </div>
    </div>
  )
}

function ParcelBody({ form }: { form: ParcelForm }) {
  return (
    <span className={cx(styles['pbody'], styles[form.is])}>
      <ParcelIcon form={form.is} />
      <span className={styles['txt']}>{form.is === 'found' ? <Chips items={form.items} /> : parcelWords(form)}</span>
      <span className={styles['short']}>{parcelShortWords(form)}</span>
    </span>
  )
}

/** On the phone the parcel is a circle with this icon only. At 1440 a finding shows its chips and no icon, unless the parcel is compact. */
function ParcelIcon({ form }: { form: ParcelForm['is'] }) {
  switch (form) {
    case 'request':
      return <IconBox strokeWidth={2.2} />
    case 'found':
      return <IconBox strokeWidth={2.2} className={styles['mini']} />
    case 'draft':
      return <IconDoc strokeWidth={2.2} />
    case 'written':
      return <IconCheck strokeWidth={2.2} />
    case 'declined':
      return <IconDash strokeWidth={2.2} />
    case 'stopped':
      return <IconX strokeWidth={2.2} />
  }
}
