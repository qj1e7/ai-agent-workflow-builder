import { describe, expect, it } from 'vitest'
import { findingItems } from './finding'
import { recording } from './recordings'

function resultOf(step: string): Record<string, unknown> {
  const event = recording('success').find((candidate) => candidate.kind === 'agent_step_finished' && candidate.data.step === step)
  if (!event || event.kind !== 'agent_step_finished') throw new Error(`no ${step} in the success recording`)
  return event.data.result
}

describe('findingItems', () => {
  it("reads the fixture's new tags and leaves the fetch count off the table", () => {
    expect(findingItems(resultOf('find_new'))).toEqual(['1.2.16', '1.2.15'])
    expect(findingItems(resultOf('fetch_releases'))).toEqual([])
  })

  it('takes only a short list of short strings', () => {
    expect(findingItems({ count: 3, latest: '1.2.16' })).toEqual([])
    expect(findingItems({ tags: [{ name: '1.2.16' }] })).toEqual([])
    expect(findingItems({ tags: ['x'.repeat(33)] })).toEqual([])
    expect(findingItems({ tags: ['1', '2', '3', '4', '5', '6', '7'] })).toEqual([])
    expect(findingItems({ tags: [] })).toEqual([])
    expect(findingItems({ tags: [' 1.2.16 ', ''] })).toEqual([])
  })

  it('trims each item and takes the first list when a result holds several', () => {
    expect(findingItems({ first: [' a ', 'b'], second: ['c'] })).toEqual(['a', 'b'])
    expect(findingItems({ count: 2, tags: ['1', '2', '3', '4', '5', '6'] })).toEqual(['1', '2', '3', '4', '5', '6'])
  })
})
