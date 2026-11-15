import { ApiError } from '../../api/client'
import type { HoldOut, Me, UseCaseN8nView, UseCaseView } from '../../api/types'
import { UNKNOWN_PUBLISHER } from './n8nChange'
import { publishedWhen, sinceWhen } from './times'

export const OPEN_IN_N8N = 'Open in n8n editor'
export const TAKE_IT_BACK = 'Take it back'
/**
 * The sketch's line beside the version says "Only our blocks are on". n8n's IF, Merge, schedule and data blocks are on too, so the
 * line names them, in the words the sketch's build panel uses for them (principle 5).
 */
export const SAFE_BLOCKS = 'Only our blocks and n8n’s safe ones are on, so every write waits for a yes.'
/** The platform's own words when it refuses to open such a workflow (builder/n8n_holds.py). */
export const DRAFT = 'Turn it on first. A draft can’t be opened in n8n.'
export const GONE = 'This workflow was deleted in n8n, so it can’t be opened there.'
export const NOT_OWN = 'This workflow has no n8n workflow of its own yet.'
const CANT_OPEN = 'n8n can’t be opened now.'
/** The workflow moved to the person's n8n space, but the platform has no address set for n8n's editor (`N8N_EDITOR_URL`). */
export const NO_EDITOR = 'It is open in your n8n space, but the platform has no address for n8n’s editor, so it can’t open it here. An admin can set it.'

/** Where the opened tab goes, or why it can't go anywhere. */
export const editorAddressOf = (held: Pick<HoldOut, 'editor_url'>): { readonly url: string } | { readonly words: string } =>
  held.editor_url ? { url: held.editor_url } : { words: NO_EDITOR }

/**
 * What this person can do with the workflow in n8n now. A hold comes first: its holder can always take it back, and so can anyone
 * else with n8n access. With nobody holding it, a deleted, draft or closed workflow says why it can't open, and draws no button.
 */
export type Hold =
  | { readonly kind: 'free' }
  | { readonly kind: 'mine'; readonly since: string; readonly editorUrl: string | null }
  /** `cant` says why this person can't take it back, or is null when they can. */
  | { readonly kind: 'theirs'; readonly name: string; readonly since: string; readonly cant: string | null }
  | { readonly kind: 'shut'; readonly words: string }

export type Held = Extract<Hold, { kind: 'mine' | 'theirs' }>

type Workflow = Pick<UseCaseView, 'state' | 'deleted_in_n8n_at'>

/** Who holds the workflow, said from this person's side, or null while it sits in the platform's own n8n project. */
export function heldOf(view: UseCaseN8nView, me: Pick<Me, 'id'>): Held | null {
  const { holder } = view
  if (!holder) return null
  if (holder.id === me.id) return { kind: 'mine', since: holder.since, editorUrl: view.editor_url }
  return { kind: 'theirs', name: holder.name, since: holder.since, cant: view.can_open ? null : (view.why_not ?? CANT_OPEN) }
}

export function holdOf(view: UseCaseN8nView, useCase: Workflow, me: Pick<Me, 'id'>): Hold {
  const held = heldOf(view, me)
  if (held) return held
  if (useCase.deleted_in_n8n_at) return { kind: 'shut', words: GONE }
  if (useCase.state === 'draft') return { kind: 'shut', words: DRAFT }
  if (!view.can_open) return { kind: 'shut', words: view.why_not ?? CANT_OPEN }
  return { kind: 'free' }
}

/** Whether this person may press Take it back: its holder may, and so may anyone else with n8n access. */
export const mayTakeBack = (held: Held): boolean => held.kind === 'mine' || held.cant === null

/** Whether Open in n8n editor is drawn: only when the platform would open it for this person. */
export const mayOpen = (hold: Hold): hold is Extract<Hold, { kind: 'free' | 'mine' }> => hold.kind === 'free' || hold.kind === 'mine'

/** The sketch's "Version 4, published by Alice, just now". A draft is saved, not published. */
export function inUseLine(view: Pick<UseCaseN8nView, 'version' | 'published_by' | 'published_by_name' | 'published_at'>, draft: boolean, now: Date): string {
  const who = view.published_by === null ? UNKNOWN_PUBLISHER : (view.published_by_name ?? view.published_by)
  return `Version ${String(view.version)}, ${draft ? 'saved as a draft' : 'published'} by ${who}, ${publishedWhen(view.published_at, now)}`
}

/** "Alice has it open in n8n since 10:02.", the platform's words for a hold, or the same said to its holder. */
export function heldLine(hold: Held, now: Date): string {
  const since = sinceWhen(hold.since, now)
  return hold.kind === 'mine' ? `You have it open in n8n since ${since}.` : `${hold.name} has it open in n8n since ${since}.`
}

/** Under a hold someone else has: that anyone with n8n access may take it back, by design (ENGINE-PLAN 2.9), or why this person can't. */
export const theirsNote = (hold: Extract<Hold, { kind: 'theirs' }>): string => hold.cant ?? `Anyone with n8n access can take it back from ${hold.name}.`

export const takenBackWords = (hold: Held): string =>
  `Taken back from ${hold.kind === 'mine' ? 'your n8n space' : hold.name}. You can change it here again.`

/** Why opening n8n or taking a workflow back was refused, in the platform's own words when it gave them. */
export function n8nRefusalWords(error: unknown, otherwise: (error: unknown) => string): string {
  if (error instanceof ApiError && [403, 409, 503].includes(error.status)) {
    const detail = (error.body as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') return detail
  }
  return otherwise(error)
}

/**
 * A tab opened by the press itself, before the platform answers, so no popup blocker stops it. It is cut off from this page at
 * once, then pointed at the editor, or closed when the platform refuses.
 */
export interface EditorTab {
  go(this: void, url: string): void
  close(this: void): void
}

export function openEditorTab(host: Pick<Window, 'open'>): EditorTab | null {
  const tab = host.open('', '_blank')
  if (!tab) return null
  tab.opener = null
  // A browser may hand back the blank page before it has a body. The words are only a courtesy, so the move never waits on them.
  const body = tab.document.body as HTMLElement | null
  if (body) body.textContent = 'Opening n8n…'
  return {
    go: (url) => tab.location.replace(url),
    close: () => tab.close(),
  }
}
