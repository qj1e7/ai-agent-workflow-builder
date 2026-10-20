const MAX_ITEMS = 6
const MAX_ITEM_CHARS = 32

function isChipList(value: unknown): value is readonly string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_ITEMS) return false
  return value.every((item) => typeof item === 'string' && item.trim().length >= 1 && item.trim().length <= MAX_ITEM_CHARS)
}

/**
 * The chips a finished step puts on the table: the first value of its result that is a short list of
 * short strings. A count, a version string or a list of objects is not a finding, so the table stays empty.
 */
export function findingItems(result: Record<string, unknown>): string[] {
  for (const value of Object.values(result)) {
    if (isChipList(value)) return value.map((item) => item.trim())
  }
  return []
}
