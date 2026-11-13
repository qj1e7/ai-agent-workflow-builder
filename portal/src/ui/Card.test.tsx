import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

describe('a card in the chat', () => {
  const html = renderToStaticMarkup(
    <Card title="Workflows" pill={<span>2</span>} status="Saved as version 3." actions={<button type="button">Open</button>}>
      <p>Two rows</p>
    </Card>,
  )

  it('is a region named by its bold title, with the pill on the same line', () => {
    const id = /<h3 id="([^"]+)"[^>]*>Workflows<\/h3>/.exec(html)?.[1]
    expect(html).toMatch(new RegExp(`<section[^>]*aria-labelledby="${id ?? '-'}"`))
    expect(text(html)).toMatch(/^Workflows 2 Two rows/)
  })

  it('ends with a foot: what happened on the left, then its buttons', () => {
    expect(text(html)).toMatch(/Two rows Saved as version 3\. Open$/)
  })

  it('has no foot when there is nothing to say or press', () => {
    const bare = renderToStaticMarkup(<Card title="What I can do">body</Card>)
    expect(text(bare)).toBe('What I can do body')
    expect(bare.match(/<div/g)).toHaveLength(1)
  })
})
