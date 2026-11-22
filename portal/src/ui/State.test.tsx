import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { StateMark, StatePill, type StateTone } from './State'

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

/** The shape each state draws, read off the SVG: a tick's path, a filled dot, a clock's ring and hands, a cross, or an empty ring. */
function shapeOf(svg: string): string {
  if (/<circle[^>]*fill="currentColor"/.test(svg)) return 'dot'
  if (/<circle[^>]*fill="none"[^>]*>(<\/circle>)?<path/.test(svg)) return 'clock'
  if (/<circle[^>]*fill="none"/.test(svg)) return 'ring'
  if (/<path d="M[\d.]+ [\d.]+l[\d.]+ [\d.]+ [\d.]+-[\d.]+"/.test(svg)) return 'tick'
  if (/<path d="M[\d.]+ [\d.]+l[\d.]+ [\d.]+M/.test(svg)) return 'cross'
  return 'none'
}

describe('a state pill', () => {
  it.each<[StateTone, string, string]>([
    ['ok', 'Done', 'tick'],
    ['on', 'On', 'dot'],
    ['run', 'Running', 'dot'],
    ['wait', 'Waiting for a yes', 'clock'],
    ['stop', 'Stopped', 'cross'],
    ['off', 'Paused', 'ring'],
  ])('draws %s as “%s” beside its shape, so the state is never colour alone', (tone, word, shape) => {
    const html = renderToStaticMarkup(<StatePill tone={tone}>{word}</StatePill>)
    expect(text(html)).toBe(word)
    expect(html).toContain(`data-tone="${tone}"`)
    expect(shapeOf(html), `${tone}'s shape`).toBe(shape)
    expect(html, 'the shape is decoration, the word is read').toMatch(/<svg[^>]*aria-hidden="true"/)
  })

  it('passes on what a screen marks it with, such as the run pill tests find it by', () => {
    const html = renderToStaticMarkup(
      <StatePill tone="stop" data-run-pill="">
        Stopped
      </StatePill>,
    )
    expect(html).toMatch(/^<span[^>]*data-run-pill=""/)
  })
})

describe('a state mark beside a name', () => {
  it.each<[StateTone, string, string]>([
    ['on', 'On', 'dot'],
    ['ok', 'Working', 'dot'],
    ['run', 'Running', 'dot'],
    ['wait', 'Waiting for a yes', 'clock'],
    ['stop', 'Stopped', 'cross'],
    ['off', 'Draft', 'ring'],
  ])('draws %s as its shape, with “%s” read out and shown on hover', (tone, word, shape) => {
    const html = renderToStaticMarkup(<StateMark tone={tone} word={word} />)
    expect(html).toMatch(new RegExp(`^<svg[^>]*role="img"[^>]*aria-label="${word}"`))
    expect(html).toContain(`<title>${word}</title>`)
    expect(shapeOf(html), `${tone}'s shape`).toBe(shape)
  })
})
