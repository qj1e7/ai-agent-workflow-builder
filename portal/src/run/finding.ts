const MAX_ITEMS = 6
const MAX_ITEM_CHARS = 32

function isChipList(value: unknown): value is readonly string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_ITEMS) return false
  return value.every((item) => typeof item === 'string' && item.trim().length >= 1 && item.trim().length <= MAX_ITEM_CHARS)
}

export function findingItems(result: Record<string, unknown>): string[] {
  for (const value of Object.values(result)) {
    if (isChipList(value)) return value.map((item) => item.trim())
  }
  return []
}
