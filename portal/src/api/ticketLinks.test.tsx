import { QueryClient } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { TicketLink } from '../screens/jira/TicketKeys'
import { parseConfig } from './config'
import { invalidateAfterMarkDone } from './queries'
import { TicketLinksProvider } from './ticketLinks'

function linkFor(raw: unknown): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <TicketLinksProvider config={parseConfig(raw)}>
        <TicketLink ticketKey="OPS-3" />
      </TicketLinksProvider>
    </MemoryRouter>,
  )
}

describe('the Jira address from /config.json', () => {
  it('turns a ticket key into a safe outside link to that Jira', () => {
    const html = linkFor({ mode: 'live', jira_browse_url: 'https://jira.example.test/browse/{key}' })
    expect(html).toMatch(/<a\b[^>]*href="https:\/\/jira.example.test\/browse\/OPS-3"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/)
    expect(html).toContain('opens Jira in a new tab')
  })

  it('turns a ticket key into a link to the practice Jira page when the file gives no address', () => {
    const html = linkFor({ mode: 'live' })
    expect(html).toContain('href="/jira/OPS-3"')
    expect(html).not.toContain('target=')
  })
})

describe('marking a ticket Done', () => {
  it('makes the tickets and the Software watchlist read again, because the watchlist moves our version', async () => {
    const queryClient = new QueryClient()
    const spy = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()
    await invalidateAfterMarkDone(queryClient)
    expect(spy.mock.calls.map(([filter]) => filter?.queryKey)).toEqual([['jira-tickets'], ['watchlist']])
  })
})
