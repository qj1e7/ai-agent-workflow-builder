function isItemList(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'string' && item.trim().length > 0)
}

/** Every item of the first list of non-empty strings in a step's result, trimmed, in order. [] when there is none. */
export function findingItems(result: Record<string, unknown>): string[] {
  for (const value of Object.values(result)) {
    if (isItemList(value)) return value.map((item) => item.trim())
  }
  return []
}
