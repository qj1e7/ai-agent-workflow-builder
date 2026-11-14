import type { ChangedInN8nReply } from '../../api/types'
import { refusedLine, SETTINGS_SAVED, UNKNOWN_PUBLISHER, UNKNOWN_PUBLISHER_STOPS } from '../workflows/n8nChange'

/** Where a Changed in n8n card is. It ends settled, or it shows why the platform said no. */
export type Phase =
  | { readonly kind: 'open' }
  | { readonly kind: 'settled'; readonly version: number }
  /** Someone changed it again in n8n, so nothing was saved. The buttons come back, as in the sketch. */
  | { readonly kind: 'lost'; readonly words: string }
  /** Another version is in use by now, so the card offers nothing more. */
  | { readonly kind: 'moved'; readonly words: string }
  /** Any other refusal, in the platform's words. The buttons stay. */
  | { readonly kind: 'refused'; readonly words: string }

export const OPEN: Phase = { kind: 'open' }

const LOST = 'Changed again since, in n8n.'
const MOVED = 'Another version is in use by now'

/** What the platform's refusal means for the card, read from its words. */
export function refusedPhase(words: string): Phase {
  if (words.startsWith(LOST)) return { kind: 'lost', words }
  if (words.startsWith(MOVED)) return { kind: 'moved', words }
  return { kind: 'refused', words }
}

export const doneWords = (version: number): string => `Done. Version ${version} is in use.`
export const inUseWords = (inUse: number): string => `Version ${inUse} is in use now.`

export const SAY_CHECKED = 'I checked the new version.'
export const SAY_CHECKED_FIX = 'I checked the new version. It needs a fix.'

export const sayChanged = (reply: Pick<ChangedInN8nReply, 'grade'>): string => (reply.grade === 'safe' ? SAY_CHECKED : SAY_CHECKED_FIX)

export interface ChangedWords {
  /** "FastAPI release check, version 4, by Alice Tan." */
  readonly who: string
  /** Said under the line above when nobody can be named. */
  readonly unknown: string | null
  readonly changes: readonly string[]
  /** Why the version is not safe, as the safety checker says it. */
  readonly findings: readonly string[]
  /** What happens to the next run when the writes are refused. */
  readonly refused: string | null
}

export function wordsOf(reply: ChangedInN8nReply): ChangedWords {
  // A save of the settings in n8n publishes nothing, and n8n names nobody for it.
  const saved = reply.made === 'settings_changed_in_n8n'
  const by = reply.by === null ? UNKNOWN_PUBLISHER : (reply.by_name ?? reply.by)
  return {
    who: saved ? `${reply.name}, version ${reply.version}. ${SETTINGS_SAVED}` : `${reply.name}, version ${reply.version}, by ${by}.`,
    unknown: reply.by === null && !saved ? UNKNOWN_PUBLISHER_STOPS : null,
    changes: reply.changes,
    findings: reply.grade === 'needs_a_fix' ? reply.findings : [],
    refused: reply.grade === 'writes_refused' ? refusedLine(reply.changes) : null,
  }
}

export interface Buttons {
  readonly yes: boolean
  readonly undo: boolean
}

const NONE: Buttons = { yes: false, undo: false }

/**
 * The card's buttons. Only an Operator changes anything, and only while the version it names is the one in use. Add the yes back
 * comes only with refused writes. Undo is always there, and goes to the version before.
 */
export function buttonsOf(reply: ChangedInN8nReply, phase: Phase, operator: boolean): Buttons {
  if (!operator || reply.in_use !== reply.version || phase.kind === 'settled' || phase.kind === 'moved') return NONE
  return { yes: reply.grade === 'writes_refused', undo: reply.version > 1 }
}

/** The line at the left of the foot, or null. */
export function statusOf(reply: Pick<ChangedInN8nReply, 'in_use' | 'version'>, phase: Phase): { readonly words: string; readonly good: boolean } | null {
  if (phase.kind === 'settled') return { words: doneWords(phase.version), good: true }
  if (reply.in_use !== reply.version) return { words: inUseWords(reply.in_use), good: false }
  return null
}

/** The refusal under the card, or null. */
export const problemOf = (phase: Phase): string | null => (phase.kind === 'lost' || phase.kind === 'moved' || phase.kind === 'refused' ? phase.words : null)

/** A Changed in n8n reply on Home, as the chat shows it: no person's words came before it. */
export const arrivalKey = (reply: Pick<ChangedInN8nReply, 'use_case_id' | 'version'>): string => `${reply.use_case_id}:${reply.version}`

/** The replies the chat has not shown yet, oldest first, so they arrive in the order they were found. Home lists the newest first. */
export function unseenArrivals(found: readonly ChangedInN8nReply[], seen: ReadonlySet<string>): ChangedInN8nReply[] {
  return found.filter((reply) => !seen.has(arrivalKey(reply))).reverse()
}
