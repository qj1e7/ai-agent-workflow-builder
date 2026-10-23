import type { Ms } from './brand'
import type { Figure, GateState, ParcelForm, Stop, StopKey, StopState, Track } from './track'

/** One thing that moves in a beat. Stops are indexes into the track after the beat. */
export type Act =
  /** The stop set changed: the line crossfades once, first. */
  | { readonly what: 'relayout' }
  | { readonly what: 'leave'; readonly figure: string; readonly stop: number }
  | { readonly what: 'arrive'; readonly figure: string; readonly stop: number }
  /** A figure became the one acting. */
  | { readonly what: 'nod'; readonly figure: string; readonly stop: number }
  | { readonly what: 'arm'; readonly stop: number; readonly from: GateState; readonly to: GateState }
  | { readonly what: 'node'; readonly stop: number; readonly to: StopState }
  /** The parcel moves and the filled rail follows it. from is null when the parcel first appears. */
  | { readonly what: 'travel'; readonly from: number | null; readonly to: number; readonly toBefore: boolean }
  | { readonly what: 'form'; readonly to: ParcelForm['is']; readonly shake: boolean }
  | { readonly what: 'break'; readonly stop: number }
  | { readonly what: 'speech'; readonly stop: number }
  | { readonly what: 'panel'; readonly stop: number }

export interface TimedAct {
  readonly act: Act
  readonly delayMs: Ms
  readonly durationMs: Ms
}

export interface BeatPlan {
  /** The director's beat key, "take:seq", so a replayed seq plays again. */
  readonly key: string
  /** cut: frames were skipped by a snap; there are no acts and the line crossfades. */
  readonly entry: 'continuous' | 'cut'
  /** In order, back to back, never overlapping. */
  readonly acts: readonly TimedAct[]
}

export interface BeatTiming {
  readonly key: string
  readonly entry: 'continuous' | 'cut'
  readonly durationMs: Ms
  /** The beat's 1x length: the plan is laid out at it, then scaled to durationMs. */
  readonly baseMs: Ms
}

/** Each act's length at 1x, from the template's motion. A form change into 'stopped' shakes and takes `shake`. */
export const ACT_MS = {
  relayout: 220,
  leave: 200,
  arrive: 360,
  nod: 420,
  arm: 700,
  node: 240,
  travel: 900,
  form: 320,
  shake: 450,
  break: 500,
  speech: 300,
  panel: 320,
} as const

/** Acts fill this share of the beat; the rest is a hold, so the new state is seen. */
export const PLAYABLE_SHARE = 0.9
/** The travel takes up to this share of the playable time, and never more than ACT_MS.travel. */
export const TRAVEL_SHARE = 0.65

type Kind = Act['what']

/** Within each group, acts play in this order. */
const ORDER: readonly Kind[] = ['leave', 'arrive', 'nod', 'arm', 'node', 'form', 'break', 'speech']
const AT_ORIGIN: ReadonlySet<Kind> = new Set(['leave', 'arrive', 'nod', 'arm', 'node'])

/**
 * What moves during one beat, from the track before it and the track after it. One thing moves at a time:
 * the relayout, then the acts at the parcel's origin stop (so the seat becomes Bob and the arm lifts before
 * the parcel leaves the gate), then the travel, then the acts elsewhere, then the panel.
 */
export function choreograph(before: Track, after: Track, beat: BeatTiming): BeatPlan {
  if (beat.entry === 'cut') return { key: beat.key, entry: beat.entry, acts: [] }
  return { key: beat.key, entry: beat.entry, acts: schedule(order(diff(before, after)), beat) }
}

function figureKeys(stop: Stop | undefined): Set<string> {
  return new Set((stop?.cast ?? []).map((figure) => figure.key))
}

function acting(track: Track): { readonly figure: string; readonly stop: StopKey } | null {
  for (const stop of track.stops) {
    const figure = stop.cast.find((candidate): candidate is Exclude<Figure, { is: 'seat' }> => candidate.is !== 'seat' && candidate.acting)
    if (figure) return { figure: figure.key, stop: stop.key }
  }
  return null
}

function stopKeyAt(track: Track, index: number | null): StopKey | null {
  return index === null ? null : (track.stops[index]?.key ?? null)
}

function diff(before: Track, after: Track): Act[] {
  const acts: Act[] = []
  const beforeStops = new Map(before.stops.map((stop) => [stop.key, stop]))
  const indexAfter = new Map(after.stops.map((stop, index) => [stop.key, index]))
  if (before.stops.length !== after.stops.length || before.stops.some((stop, index) => stop.key !== after.stops[index]?.key)) {
    acts.push({ what: 'relayout' })
  }

  after.stops.forEach((stop, index) => {
    const was = beforeStops.get(stop.key)
    const had = figureKeys(was)
    const has = figureKeys(stop)
    for (const figure of had) if (!has.has(figure)) acts.push({ what: 'leave', figure, stop: index })
    for (const figure of has) if (!had.has(figure)) acts.push({ what: 'arrive', figure, stop: index })
    if (was && was.state !== stop.state) acts.push({ what: 'node', stop: index, to: stop.state })
  })

  const nowActing = acting(after)
  const wasActing = acting(before)
  const actingStop = nowActing ? indexAfter.get(nowActing.stop) : undefined
  if (nowActing && actingStop !== undefined && (nowActing.figure !== wasActing?.figure || nowActing.stop !== wasActing.stop)) {
    acts.push({ what: 'nod', figure: nowActing.figure, stop: actingStop })
  }

  if (after.gate && (before.gate?.state ?? 'idle') !== after.gate.state) {
    acts.push({ what: 'arm', stop: after.gate.stop, from: before.gate?.state ?? 'idle', to: after.gate.state })
  }

  const parcel = after.parcel
  if (parcel) {
    const from = before.parcel ? stopKeyAt(before, before.parcel.at) : null
    if (!before.parcel || from !== stopKeyAt(after, parcel.at) || before.parcel.before !== parcel.before) {
      acts.push({ what: 'travel', from: from === null ? null : (indexAfter.get(from) ?? null), to: parcel.at, toBefore: parcel.before })
    }
    if (before.parcel && JSON.stringify(before.parcel.form) !== JSON.stringify(parcel.form)) {
      acts.push({ what: 'form', to: parcel.form.is, shake: parcel.form.is === 'stopped' })
    }
  }

  if (after.breakAt !== null && before.breakAt === null) acts.push({ what: 'break', stop: after.breakAt })
  if (after.speech && after.speech.seq !== before.speech?.seq) acts.push({ what: 'speech', stop: after.speech.stop })

  const panel = after.panel
  if (panel && (before.panel?.is !== panel.is || stopKeyAt(before, before.panel.stop) !== stopKeyAt(after, panel.stop))) {
    acts.push({ what: 'panel', stop: panel.stop })
  }
  return acts
}

function rank(act: Act): number {
  return ORDER.indexOf(act.what)
}

function order(acts: readonly Act[]): Act[] {
  const travel = acts.find((act): act is Extract<Act, { what: 'travel' }> => act.what === 'travel')
  const origin = travel?.from ?? null
  const atOrigin = (act: Act) => origin !== null && AT_ORIGIN.has(act.what) && 'stop' in act && act.stop === origin
  const byOrder = (a: Act, b: Act) => rank(a) - rank(b)
  const rest = acts.filter((act) => act.what !== 'relayout' && act.what !== 'travel' && act.what !== 'panel' && !atOrigin(act))
  return [
    ...acts.filter((act) => act.what === 'relayout'),
    ...acts.filter(atOrigin).sort(byOrder),
    ...(travel ? [travel] : []),
    ...rest.sort(byOrder),
    ...acts.filter((act) => act.what === 'panel'),
  ]
}

function lengthOf(act: Act): Ms {
  return act.what === 'form' && act.shake ? ACT_MS.shake : ACT_MS[act.what]
}

/**
 * Laid out at the beat's 1x length: the playable time is PLAYABLE_SHARE of it, the travel takes
 * min(ACT_MS.travel, TRAVEL_SHARE of the playable time), and the other acts share the rest in order, each
 * scaled by one factor and never longer than its own length. Then every time scales with the beat, so 2x
 * halves the plan exactly. Positions are rounded once, so acts stay back to back.
 */
function schedule(acts: readonly Act[], beat: BeatTiming): TimedAct[] {
  const base = beat.baseMs > 0 ? beat.baseMs : beat.durationMs
  const scale = base > 0 ? beat.durationMs / base : 0
  const playable = PLAYABLE_SHARE * base
  const travelMs = acts.some((act) => act.what === 'travel') ? Math.min(ACT_MS.travel, TRAVEL_SHARE * playable) : 0
  const others = acts.reduce((sum, act) => (act.what === 'travel' ? sum : sum + lengthOf(act)), 0)
  const k = others > 0 ? Math.min(1, (playable - travelMs) / others) : 1
  let start = 0
  return acts.map((act) => {
    const end = start + (act.what === 'travel' ? travelMs : lengthOf(act) * k)
    const delayMs = Math.round(start * scale)
    const timed = { act, delayMs, durationMs: Math.round(end * scale) - delayMs }
    start = end
    return timed
  })
}
