import type { DataOf, EventKind } from '../stream/parse'
import type { Ms } from './brand'

/**
 * The two fields a rule reads. A parsed RunEvent and a wire ActivityEvent both carry them, so one
 * table paces the room and the demo platform's recording alike.
 */
export type BeatEvent = { [K in EventKind]: { readonly kind: K; readonly data: DataOf<K> } }[EventKind] | { readonly kind: 'opaque' }

export type KindRule =
  /** Workflow plumbing and anything unreadable. Folded silently, no beat, no caption. Minutes only with technical details. */
  | { readonly tier: 'technical' }
  /**
   * One beat. beatMs is the choreographed duration (replay and calm live play). floorMs is the shortest
   * live catch-up may squeeze it to, so every state stays perceivable. caption false keeps the event in
   * the Minutes but out of the live caption, for a step that starts and ends within a second.
   */
  | { readonly tier: 'story'; readonly beatMs: Ms; readonly floorMs: Ms; readonly caption: boolean }

type StoryRule = Extract<KindRule, { tier: 'story' }>

const technical: KindRule = { tier: 'technical' }
const story = (beatMs: Ms, floorMs: Ms, caption = true): StoryRule => ({ tier: 'story', beatMs, floorMs, caption })

/**
 * Durations follow DESIGN.md motion rules: crossfade 180, arrivals and hand-offs 700 to 1000, the stamp
 * overshoot about 320, on one ease. A beat is the motion plus a short hold so the new state is seen.
 * `satisfies Record<EventKind, ...>` makes a kind added to the contract a type error until it has a row.
 */
export const KINDS = {
  run_created: story(900, 600),
  leg_dispatched: technical,
  step_started: technical,
  step_finished: technical,
  step_retried: technical,
  agent_joined: story(1000, 400),
  agent_step_started: story(900, 300, false),
  agent_step_finished: story(1400, 400),
  agent_failed: story(1200, 700),
  agent_message: story(2200, 1200),
  write_action_proposed: story(1400, 600),
  approval_requested: story(1600, 900),
  approval_announced: story(1000, 400),
  approval_announce_failed: story(1200, 700),
  approval_decided: story(1800, 900),
  write_action_denied: story(1400, 800),
  write_action_done: story(2200, 1400),
  run_succeeded: story(1200, 600),
  run_rejected: story(1200, 600),
  run_failed: story(1400, 800),
  run_retried: story(1200, 600),
} as const satisfies Record<EventKind, KindRule>

export const READING = { baseMs: 1200, perCharMs: 25, maxMs: 4000 } as const

/** Catch-up never squeezes speech below this. */
export function readingMsOf(text: string): Ms {
  return Math.min(READING.maxMs, READING.baseMs + READING.perCharMs * text.length)
}

export function ruleOf(e: BeatEvent): KindRule {
  if (e.kind === 'opaque') return technical
  if (e.kind === 'agent_message') {
    const reading = readingMsOf(e.data.text)
    return story(Math.max(KINDS.agent_message.beatMs, reading), reading)
  }
  return KINDS[e.kind]
}

export function isStory(e: BeatEvent): boolean {
  return ruleOf(e).tier === 'story'
}

/** The choreographed length of an event's beat, or 0 for a technical event. */
export function beatMsOf(e: BeatEvent): Ms {
  const rule = ruleOf(e)
  return rule.tier === 'story' ? rule.beatMs : 0
}

export function floorMsOf(e: BeatEvent): Ms {
  const rule = ruleOf(e)
  return rule.tier === 'story' ? rule.floorMs : 0
}
