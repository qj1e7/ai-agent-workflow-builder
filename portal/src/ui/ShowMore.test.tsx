import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Pager } from '../api/homeQueries'
import { landing, ShowMore, shownWords } from './ShowMore'

const IDLE: Pager = { busy: false, failed: false, showMore: () => undefined }
const draw = (shown: number, total: number, pager: Pager = IDLE) => renderToStaticMarkup(<ShowMore shown={shown} total={total} pager={pager} keys={['a', 'b']} rowAttr="data-row" />)
const BEFORE: ReadonlySet<string> = new Set(['a', 'b'])

describe('the line under a list that shows part of its rows', () => {
  it('says how many show of how many, and all of them once the last arrive', () => {
    expect(shownWords(10, 27)).toBe('Showing 10 of 27.')
    expect(shownWords(27, 27)).toBe('Showing all 27.')
  })

  it('says plainly when the next page could not be read, and keeps the count', () => {
    expect(shownWords(10, 27, true)).toBe('Showing 10 of 27. I couldn’t read more just now. Try again.')
  })
})

describe('Show more', () => {
  it('is a real button the keyboard reaches, described by the line a screen reader hears change', () => {
    const html = draw(10, 27)
    const line = /<p id="([^"]+)" role="status" tabindex="-1"[^>]*>Showing 10 of 27\.<\/p>/.exec(html)
    expect(line, 'the count is a status, read out when it changes').not.toBeNull()
    expect(html).toMatch(new RegExp(`<button type="button" aria-describedby="${line?.[1] ?? ''}"[^>]*>Show more</button>`))
    expect(html, 'never disabled, so it keeps focus while it reads').not.toMatch(/disabled=""/)
  })

  it('stays focusable while the next page is read, and says it is busy', () => {
    const html = draw(10, 27, { ...IDLE, busy: true })
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*aria-busy="true"[^>]*>/)
    expect(html).not.toMatch(/disabled=""/)
  })

  it('draws nothing when the list already shows every row', () => {
    expect(draw(27, 27)).toBe('')
  })
})

describe('where focus goes after Show more', () => {
  it('waits while the page is read, and while nothing new has come and the read is not over', () => {
    expect(landing(BEFORE, ['a', 'b'], true, true, false)).toBe('waiting')
    expect(landing(BEFORE, ['a', 'b'], true, false, false)).toBe('waiting')
    expect(landing(BEFORE, ['a', 'b', 'c'], false, true, true)).toBe('waiting')
  })

  it('stays on the button when new rows came and more are left', () => {
    expect(landing(BEFORE, ['a', 'b', 'c'], true, false, true)).toBe('kept')
    expect(landing(BEFORE, ['a', 'b', 'c'], true, false, false), 'rows shown from what was already read').toBe('kept')
  })

  it('lets the press go once the read is over with nothing new, so a later refresh never moves focus', () => {
    expect(landing(BEFORE, ['a', 'b'], true, false, true)).toBe('kept')
  })

  it('moves to the first new row as drawn when the last rows arrive and the button goes', () => {
    expect(landing(BEFORE, ['c', 'a', 'd', 'b'], false, false, true)).toEqual({ row: 'c' })
  })

  it('moves to the line when the button goes with no new row, so focus is never lost', () => {
    expect(landing(BEFORE, ['a'], false, false, true)).toBe('line')
  })
})
