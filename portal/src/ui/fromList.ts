/** Router state for a page opened from a list on screen, so leaving it can go Back and the list keeps its place. */
export const FROM_LIST = { fromList: true }

export function openedFromList(state: unknown): boolean {
  return typeof state === 'object' && state !== null && 'fromList' in state
}
