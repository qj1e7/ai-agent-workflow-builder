import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { STILL_WORKING, STILL_WORKING_MS, Waiting, waitingWords } from './Waiting'

describe('the words while an answer is pending', () => {
  it('show nothing at first, as the sketch’s dots stand alone, and after 8 seconds say questions about the data take a little longer', () => {
    expect(waitingWords(0)).toEqual({ shown: null, read: 'Working on it' })
    expect(waitingWords(STILL_WORKING_MS - 1).shown).toBeNull()
    expect(waitingWords(STILL_WORKING_MS)).toEqual({ shown: 'Still working. Questions about your data take a little longer.', read: STILL_WORKING })
    expect(STILL_WORKING_MS).toBe(8000)
    expect(STILL_WORKING).not.toContain('step')
  })

  it('mounts a status region with no words, so a screen reader announces them when they arrive, and moves nothing', () => {
    const html = renderToStaticMarkup(<Waiting />)
    expect(html).toMatch(/<p [^>]*role="status"[^>]*><\/p>/)
    expect(html).not.toContain('Working on it')
    expect(html).not.toContain('style=')
  })
})
