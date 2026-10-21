import { describe, expect, it } from 'vitest'
import { createLatch } from './latch'

describe('the latch on a button that sends a request', () => {
  it('lets one press through until its request settles, so two presses in one tick send once', () => {
    const latch = createLatch()
    const sent: string[] = []
    let settle = () => undefined as void
    const press = (what: string) =>
      latch.run((settled) => {
        sent.push(what)
        settle = settled
      })
    press('approve')
    press('decline')
    expect(sent, 'the second press in the same tick').toEqual(['approve'])
    settle()
    press('approve again')
    expect(sent, 'a press after the request settled').toEqual(['approve', 'approve again'])
  })
})
