import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { FindOut } from '../../api/types'
import { NothingFound } from './WatchlistCard'

type NoMatch = Exclude<FindOut, { status: 'found' }>

const render = (answer: NoMatch) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <NothingFound name="httpx" answer={answer} />
    </MemoryRouter>,
  )
const text = (html: string) => html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")

describe('Home’s add card when the finder offers nothing', () => {
  it('says what went wrong when GitHub could not be asked, as an alert, and never that nothing was found', () => {
    const busy = "GitHub search is busy just now, so I couldn't look up httpx. Type its repository as owner/name instead, or try again later."
    const html = render({ status: 'not_checked', message: busy })
    expect(html).toContain('role="alert"')
    expect(text(html)).toContain(busy)
    expect(text(html)).not.toContain('find where')
    expect(text(html)).toContain('Add it on the Software watchlist')
  })

  it('says nothing was found, and where to add it, when the finder found nothing', () => {
    const html = render({ status: 'not_known', message: "I couldn't find httpx on our list or by searching GitHub." })
    expect(html).not.toContain('role="alert"')
    expect(text(html)).toContain('I couldn’t find where httpx is published. Add it on the Software watchlist and choose GitHub, Maven Central or npm.')
  })
})
