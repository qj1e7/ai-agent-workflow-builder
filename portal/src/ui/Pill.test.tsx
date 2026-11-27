import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Pill, pillLook } from './Pill'

describe('the one state pill', () => {
  it('is its word and nothing else inside, because the style draws the icon, so a screen reader reads one word', () => {
    expect(renderToStaticMarkup(<Pill tone="wait">Needs you</Pill>)).toMatch(/^<span class="[^"]*pill[^"]*" data-tone="wait">Needs you<\/span>$/)
  })

  it('keeps the attributes a caller gives it ahead of its own tone, so a caller can name the state it shows', () => {
    const html = renderToStaticMarkup(
      <Pill tone="bad" id="p1" data-life="on" data-run-pill>
        Stopped
      </Pill>,
    )
    expect(html).toMatch(/data-life="on"[^>]*data-tone="bad"[^>]*>Stopped<\/span>/)
    expect(html).toContain('id="p1"')
    expect(html).toContain('data-run-pill')
  })

  it("is larger in a page heading and takes the caller's own class", () => {
    const html = renderToStaticMarkup(
      <Pill large className="mine">
        Draft
      </Pill>,
    )
    expect(html).toMatch(/class="[^"]*pill[^"]*"/)
    expect(html).toMatch(/class="[^"]*large[^"]*"/)
    expect(html).toContain('mine')
    expect(html).not.toContain('data-tone')
  })

  it("draws every tone the app already uses as one of the sketch's six looks", () => {
    expect(pillLook('ok')).toBe('ok')
    expect(pillLook('good')).toBe('ok')
    expect(pillLook('on')).toBe('on')
    expect(pillLook('wait')).toBe('wait')
    expect(pillLook('bad')).toBe('err')
    expect(pillLook('new')).toBe('run')
    expect(pillLook('open')).toBe('run')
    expect(pillLook('run')).toBe('run')
    expect(pillLook('quiet')).toBe('off')
    expect(pillLook('off')).toBe('off')
    expect(pillLook(undefined)).toBe('off')
  })
})
