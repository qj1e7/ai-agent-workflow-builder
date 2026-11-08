import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { STILL_WORKING, STILL_WORKING_MS, WORKING, Waiting, waitingWords } from './Waiting'

describe('the words while an answer is pending', () => {
  it('say Working on it, then after 8 seconds that questions about the data take a little longer', () => {
    expect(waitingWords(0)).toBe('Working on it…')
    expect(waitingWords(STILL_WORKING_MS - 1)).toBe(WORKING)
    expect(waitingWords(STILL_WORKING_MS)).toBe('Still working. Questions about your data take a little longer.')
    expect(STILL_WORKING_MS).toBe(8000)
    expect(STILL_WORKING).not.toContain('step')
  })

  it('mounts a status region with no words, so a screen reader announces them when they arrive, and moves nothing', () => {
    const html = renderToStaticMarkup(<Waiting />)
    expect(html).toMatch(/<p [^>]*role="status"[^>]*><\/p>/)
    expect(html).not.toContain(WORKING)
    expect(html).not.toContain('style=')
  })
})
