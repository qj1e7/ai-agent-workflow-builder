import { describe, expect, it } from 'vitest'
import { presentNow, withLeaving, withoutGone, type Present } from './presence'

const keyOf = (item: string) => item
const keysOf = (list: readonly Present<string>[]) => list.map((p) => (p.leaving ? `${p.key}~` : p.key))

describe('a list that keeps what just left', () => {
  it('keeps a removed item where it was, marked leaving', () => {
    expect(keysOf(withLeaving(presentNow(['a', 'b', 'c', 'd'], keyOf), ['a', 'd'], keyOf))).toEqual(['a', 'b~', 'c~', 'd'])
  })

  it('adds a new item where the list puts it, and never marks it leaving', () => {
    expect(keysOf(withLeaving(presentNow(['a', 'b'], keyOf), ['c', 'a', 'b'], keyOf))).toEqual(['c', 'a', 'b'])
  })

  it('brings back an item that was leaving when it returns', () => {
    const leaving = withLeaving(presentNow(['a', 'b'], keyOf), ['a'], keyOf)
    expect(keysOf(withLeaving(leaving, ['a', 'b'], keyOf))).toEqual(['a', 'b'])
  })

  it('keeps an item leaving across another change until it is gone', () => {
    const leaving = withLeaving(presentNow(['a', 'b', 'c'], keyOf), ['a', 'c'], keyOf)
    const again = withLeaving(leaving, ['a', 'c', 'e'], keyOf)
    expect(keysOf(again)).toEqual(['a', 'b~', 'c', 'e'])
    expect(keysOf(withoutGone(again, 'b'))).toEqual(['a', 'c', 'e'])
  })

  it('takes the newest copy of an item that stays', () => {
    const [first] = withLeaving(presentNow([{ id: 'a', n: 1 }], (x) => x.id), [{ id: 'a', n: 2 }], (x) => x.id)
    expect(first?.item.n).toBe(2)
  })
})
