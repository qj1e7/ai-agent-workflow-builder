export const FROM_LIST = { fromList: true }

export function openedFromList(state: unknown): boolean {
  return typeof state === 'object' && state !== null && 'fromList' in state
}
