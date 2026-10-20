import type { EventKind, RunEvent } from '../stream/parse'
import type { Ms } from './brand'

export type KindRule =
  /** Workflow plumbing and anything unreadable. Folded silently, no beat, no caption. Minutes only with technical details. */
  | { readonly tier: 'technical' }
  /**
   * One beat. beatMs is the choreographed duration (replay and calm live play). floorMs is the shortest
   * live catch-up may squeeze it to, so every state stays perceivable.
   */
  | { readonly tier: 'story'; readonly beatMs: Ms; readonly floorMs: Ms }

type StoryRule = Extract<KindRule, { tier: 'story' }>

const technical: KindRule = { tier: 'technical' }
const story = (beatMs: Ms, floorMs: Ms): StoryRule => ({ tier: 'story', beatMs, floorMs })

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
  agent_step_started: story(900, 300),
  agent_step_finished: story(900, 300),
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

/** How long a message stays readable. Catch-up never squeezes speech below this; it saves its time on travel and technical beats. */
export function readingMsOf(text: string): Ms {
  return Math.min(READING.maxMs, READING.baseMs + READING.perCharMs * text.length)
}

export function ruleOf(e: RunEvent): KindRule {
  if (e.kind === 'opaque') return technical
  if (e.kind === 'agent_message') {
    const reading = readingMsOf(e.data.text)
    return story(Math.max(KINDS.agent_message.beatMs, reading), reading)
  }
  return KINDS[e.kind]
}

export function isStory(e: RunEvent): boolean {
  return ruleOf(e).tier === 'story'
}

/** The choreographed length of an event's beat, or 0 for a technical event. */
export function beatMsOf(e: RunEvent): Ms {
  const rule = ruleOf(e)
  return rule.tier === 'story' ? rule.beatMs : 0
}

export function floorMsOf(e: RunEvent): Ms {
  const rule = ruleOf(e)
  return rule.tier === 'story' ? rule.floorMs : 0
}
