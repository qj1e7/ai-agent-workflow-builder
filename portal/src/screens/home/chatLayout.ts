/** The window width from which Home's chat has room for the slim list beside it, as the sketch's 1080 px. Narrower, the pinned line is the glance. */
export const SLIM_LIST_FROM = '(min-width: 1080px)'

/**
 * What sits beside the chat. In a wide window the slim list docks there, and says what the pinned line would, so the line is dropped. An
 * open side panel takes the list's place and the line returns, as in the sketch. In a narrow window the line is the only glance.
 */
export function besideChat(wide: boolean, panelOpen: boolean): { readonly slim: boolean; readonly pinned: boolean } {
  const slim = wide && !panelOpen
  return { slim, pinned: !slim }
}
