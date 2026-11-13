import { createContext } from 'react'
import type { Form } from './card'
import type { Phase as EditPhase, Picks } from './edit'
import type { Phase } from './SetupCard'

/** Where a set-up card is when its page is left: what is on it, the draft it keeps, and whether it is still open. */
export interface CardKept {
  readonly form: Form
  readonly draft: string | null
  readonly phase: Phase
}

/** Where an edit card is when its page is left: what she picked, and whether she saved, undid or backed out. */
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
  /** The run a run card follows, so it keeps following it after a retry takes the run off the stopped list. */
  readonly run: Slot<string>
}

export function newCardMemory(): CardMemory {
  return { ...slot<CardKept>(), edit: slot<EditKept>(), run: slot<string>() }
}

const forgets = <T,>(): Slot<T> => ({ kept: () => undefined, keep: () => undefined })

export const NO_MEMORY: CardMemory = { ...forgets<CardKept>(), edit: forgets<EditKept>(), run: forgets<string>() }

export const CardMemoryContext = createContext<CardMemory>(NO_MEMORY)
