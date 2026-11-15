import { createContext, useContext } from 'react'

/**
 * The one thing the side panel shows (spec 3.3). The lists and the needs have no id. A run waiting for a yes is an approval, and
 * shows the run's content until its own view lands. The chat holds it, never the address.
 */
export type PanelItem =
  | { readonly kind: 'needs' | 'workflows' | 'watchlist'; readonly id?: undefined }
  | { readonly kind: 'workflow' | 'run' | 'approval' | 'software' | 'connection' | 'build'; readonly id: string }

export const panelKey = (item: PanelItem): string => `${item.kind}:${item.id ?? ''}`

export const sameItem = (shown: PanelItem | null, item: PanelItem): boolean => shown !== null && panelKey(shown) === panelKey(item)

/** Only the build view needs the room: the chat narrows to a column and the panel takes the rest (the sketch's `.wide`). */
export const isWide = (item: PanelItem): boolean => item.kind === 'build'

/** What Back says for the item it returns to. A list's title is fixed. A single item's name is read from its data, so the panel uses its own. */
const BACK_TITLES: Readonly<Record<PanelItem['kind'], string>> = {
  needs: 'Needs you',
  workflows: 'Workflows',
  watchlist: 'Watchlist',
  workflow: 'Workflow',
  run: 'The run',
  approval: 'Approval',
  software: 'Software',
  connection: 'Connection',
  build: 'Build',
}
export const backTitle = (item: PanelItem): string => BACK_TITLES[item.kind]

/** What the panel's bar says: the item's title, and where More details goes, or null when the item has no page to open. */
export interface PanelHead {
  readonly title: string
  readonly page: string | null
}

export interface PanelOpener {
  readonly shown: PanelItem | null
  readonly open: (item: PanelItem, from: HTMLElement) => void
  /** Shows the item beside the chat without moving focus, as an answer does on a wide screen. */
  readonly show: (item: PanelItem) => void
}

/** In the chat's thread and its pinned line, an item opens in the side panel. Anywhere else, the side panel included, it opens as its page. */
export const OpensInPanel = createContext<PanelOpener | null>(null)

/** Inside the side panel: after an action the panel goes back to its top and focuses its heading, so it stays open on what changed. */
export const InSidePanel = createContext<(() => void) | null>(null)

/** True while the side panel shows one of these items, so the chat hides its own way to open it and its own copy of the flow. */
export function useShownInPanel(...items: readonly PanelItem[]): boolean {
  const opener = useContext(OpensInPanel)
  return opener !== null && items.some((item) => sameItem(opener.shown, item))
}

export function useAfterPanelAction(): (() => void) | null {
  return useContext(InSidePanel)
}

/** Where Tab goes in a panel that covers the window: round from the last stop to the first, and back. Null lets it move as usual. */
export function wrapTab<T>(stops: readonly T[], active: unknown, back: boolean): T | null {
  const first = stops[0]
  const last = stops.at(-1)
  if (first === undefined || last === undefined) return null
  const inside = stops.some((stop) => stop === active)
  if (back) return !inside || active === first ? last : null
  return !inside || active === last ? first : null
}

interface Closing<T> {
  /** The chat's ways to open the panel's first item, in page order. */
  readonly openers: readonly T[]
  /** Which of them the person pressed, or null when an answer showed the panel by itself. */
  readonly from: number | null
  /** True when focus was in the panel, which is going, or nowhere. Read only for a panel an answer showed. */
  readonly lost: boolean
  readonly box: T | null
}

/**
 * What takes focus when the panel closes, or null to leave it where it is. A panel the person opened hands focus back to the control
 * they pressed, which shows again, else another way to open the same item. A panel an answer showed by itself was opened by nothing
 * the person pressed, so focus stays where they put it, such as in the box, and only what the panel held goes to the box.
 */
export function focusAfterClose<T>({ openers, from, lost, box }: Closing<T>): T | null {
  if (from !== null) return openers[from] ?? openers[0] ?? box
  return lost ? box : null
}
