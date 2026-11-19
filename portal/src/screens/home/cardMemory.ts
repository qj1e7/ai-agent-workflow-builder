import { createContext } from 'react'
import type { Form } from './card'
import type { Phase as EditPhase, Picks } from './edit'
import type { Phase as ChangedPhase } from './changed'
import type { Phase } from './SetupCard'
import type { ChangeFeedback } from '../software/removal'

/** Where a set-up card is when its page is left: what is on it, the draft it keeps, and whether it is still open. */
export interface CardKept {
  readonly form: Form
  readonly draft: string | null
  readonly phase: Phase
}

/** Where an edit card is when its page is left: what they picked, and whether they saved, undid or backed out. */
export interface EditKept {
  readonly picks: Picks
  readonly phase: EditPhase
}

interface Slot<T> {
  readonly kept: () => T | undefined
  readonly keep: (kept: T) => void
}

function slot<T>(): Slot<T> {
  let kept: T | undefined
  return {
    kept: () => kept,
    keep: (next) => {
      kept = next
    },
  }
}

/**
 * The chat keeps its conversation across pages, but a card is drawn again when Home comes back. This hands the card what it
 * had, so it carries on with the same draft and never turns on twice, and an edit card keeps its Undo. One message keeps the
 * same memory for as long as the chat does.
 */
export interface CardMemory extends Slot<CardKept> {
  readonly edit: Slot<EditKept>
  /** Whether this answer has already shown its item beside the chat, so coming back to the chat never opens it again. */
  readonly beside: Slot<true>
  /** The run a run card follows, so it keeps following it after a retry takes the run off the stopped list. */
  readonly run: Slot<string>
  /** The requests approval cards follow, so each keeps its record after a decision takes it off the waiting list. */
  readonly approvals: Slot<readonly RequestRef[]>
  /** Where a Changed in n8n card is, so a card that settled still says so when Home comes back. */
  readonly changed: Slot<ChangedPhase>
  /** What each row of a remove card last said, by software id, so its Undo is still there when Home comes back. */
  readonly removals: Slot<Readonly<Record<string, ChangeFeedback['notice']>>>
  /** True while an Explain card shows code's wording instead of the reworded one, so a swap stays when Home comes back. */
  readonly wording: Slot<boolean>
  /** The workflow “explain it” meant when the answer arrived, or null for none, so the card doesn't change as the side panel does. */
  readonly focus: Slot<string | null>
}

/** One request a card follows: the run it opens as, and its approval, or null until the run names it. */
export interface RequestRef {
  readonly approvalId: string | null
  readonly runId: string
}

export function newCardMemory(): CardMemory {
  return { ...slot<CardKept>(), edit: slot<EditKept>(), beside: slot<true>(), run: slot<string>(), approvals: slot<readonly RequestRef[]>(), changed: slot<ChangedPhase>(), removals: slot<Readonly<Record<string, ChangeFeedback['notice']>>>(), wording: slot<boolean>(), focus: slot<string | null>() }
}

const forgets = <T,>(): Slot<T> => ({ kept: () => undefined, keep: () => undefined })

export const NO_MEMORY: CardMemory = { ...forgets<CardKept>(), edit: forgets<EditKept>(), beside: forgets<true>(), run: forgets<string>(), approvals: forgets<readonly RequestRef[]>(), changed: forgets<ChangedPhase>(), removals: forgets<Readonly<Record<string, ChangeFeedback['notice']>>>(), wording: forgets<boolean>(), focus: forgets<string | null>() }

export const CardMemoryContext = createContext<CardMemory>(NO_MEMORY)
