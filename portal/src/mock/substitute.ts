export type Replacement = readonly [from: string, to: string]

const MARK = '\u0001'

// Two passes through placeholders, so a replaced name is never replaced again by a later rule.
export function substitute<T>(value: T, replacements: readonly Replacement[]): T {
  let text = JSON.stringify(value)
  replacements.forEach(([from], index) => {
    text = text.replaceAll(from, `${MARK}${index}${MARK}`)
  })
  replacements.forEach(([, to], index) => {
    text = text.replaceAll(`${MARK}${index}${MARK}`, JSON.stringify(to).slice(1, -1))
  })
  return JSON.parse(text) as T
}
