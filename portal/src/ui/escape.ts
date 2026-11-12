/**
 * One Escape closes one thing. Whatever takes it calls preventDefault, and the innermost goes first: a menu, an editor or a
 * dialog, then the side panel, which listens on the document, then a message at the bottom of the page, which listens on the
 * window, after everything else.
 */
export function escapeIsFree(event: { readonly key: string; readonly defaultPrevented: boolean }, dialogOpen: boolean): boolean {
  return event.key === 'Escape' && !event.defaultPrevented && !dialogOpen
}
