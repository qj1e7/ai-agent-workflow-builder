import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { StateMark } from './StateMark'

describe('the state mark', () => {
  it('is one picture, named and titled with the state’s words, and holds no text', () => {
    const html = renderToStaticMarkup(<StateMark tone="wait" label="On · waiting for approval" />)
    expect(html).toContain('role="img"')
    expect(html).toContain('aria-label="On · waiting for approval"')
    expect(html).toContain('title="On · waiting for approval"')
    expect(html.replace(/<[^>]*>/g, '')).toBe('')
  })

  it('draws the pill’s look for a tone, and the grey ring for none', () => {
    expect(renderToStaticMarkup(<StateMark tone="bad" label="Needs you" />)).toContain('data-look="err"')
    expect(renderToStaticMarkup(<StateMark tone="on" label="On" />)).toContain('data-look="on"')
    expect(renderToStaticMarkup(<StateMark tone={undefined} label="Paused" />)).toContain('data-look="off"')
  })
})
