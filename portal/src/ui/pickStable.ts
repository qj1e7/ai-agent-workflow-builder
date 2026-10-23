function stableHash(text: string): number {
  let hash = 5381
  for (const char of text) hash = (Math.imul(hash, 33) + (char.codePointAt(0) ?? 0)) >>> 0
  return hash
}

/** The same key always gets the same choice, so a name keeps its colours on every screen and in every run. */
export function pickStable<T>(choices: readonly [T, ...T[]], key: string): T {
  return choices[stableHash(key) % choices.length] ?? choices[0]
}
