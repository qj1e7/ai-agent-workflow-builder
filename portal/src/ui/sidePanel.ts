import { createContext, useContext, type ReactNode } from 'react'

/**
 * The one item the side panel shows (spec 3.3). A run waiting for a yes shows its approval, so an approval opens as its run.
 * The chat holds it, never the address.
 */
export interface PanelItem {
  readonly kind: 'workflow' | 'run' | 'software'
  readonly id: string
}

export const panelKey = (item: PanelItem): string => `${item.kind}:${item.id}`

/** What a view gives the panel's bar and body. `page` is where More details goes, or null when the item has no page to open. */
export interface PanelView {
  readonly title: string
  readonly page: string | null
  readonly body: ReactNode
}

/** Each kind's view reads its own data and hands the panel what to draw. */
export interface PanelViewProps {
  readonly id: string
  readonly children: (view: PanelView) => ReactNode
}

export const sameItem = (shown: PanelItem | null, item: PanelItem): boolean => shown !== null && shown.kind === item.kind && shown.id === item.id

export interface PanelOpener {
  readonly shown: PanelItem | null
  readonly open: (item: PanelItem, from: HTMLElement) => void
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

/** Escape closes the panel, unless a dialog over it, such as Teams, or the control with focus took the key first. */
export function escapeCloses(event: { readonly key: string; readonly defaultPrevented: boolean }, dialogOpen: boolean): boolean {
  return event.key === 'Escape' && !event.defaultPrevented && !dialogOpen
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

/** What takes focus when the panel closes: the control that opened it, which shows again, else another way to open the same item. */
export function openerAfterClose<T>(openers: readonly T[], from: number): T | null {
  return openers[from] ?? openers[0] ?? null
}
