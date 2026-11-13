import { describe, expect, it } from 'vitest'
import { foldSender, type Transition } from './fold'

describe('the first message folding the hero into the chat', () => {
  it('ignores a second Enter or a chip press while the fold waits for the browser, then sends the first message once', () => {
    const held: (() => void)[] = []
    const transition: Transition = (update) => void held.push(update)
    const holds: boolean[] = []
    const sent: string[] = []
    const send = foldSender((on) => holds.push(on))

    expect(send(() => sent.push('first'), transition)).toBe(true)
    expect(sent, 'the browser has not run the fold yet').toEqual([])
    expect(holds, 'the box and chips are held').toEqual([true])
    expect(send(() => sent.push('second, by Enter'), transition), 'a second Enter is ignored').toBe(false)
    expect(send(() => sent.push('a chip'), null), 'a chip press is ignored').toBe(false)

    held.forEach((update) => update())
    expect(sent).toEqual(['first'])
    expect(holds).toEqual([true, false])
    expect(send(() => sent.push('after the fold'), null)).toBe(true)
    expect(sent).toEqual(['first', 'after the fold'])
  })

  it('sends at once, holding nothing, when there is no transition, as with reduced motion', () => {
    const holds: boolean[] = []
    const sent: string[] = []
    const send = foldSender((on) => holds.push(on))
    expect(send(() => sent.push('hi'), null)).toBe(true)
    expect(sent).toEqual(['hi'])
    expect(holds).toEqual([])
  })
})
