import teams from '@contracts/fixtures/stubs/teams-messages.json'
import decided from '@contracts/fixtures/stubs/teams-messages.decided.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { AdaptiveCard, TeamsStubMessage } from '../api/types'
import { AdaptiveCardView, inAppPath } from './TeamsCard'

const WAITING = (teams.messages[0] as TeamsStubMessage).card as AdaptiveCard
const DECIDED = (decided.messages[0] as TeamsStubMessage).card as AdaptiveCard
const OPEN_URL = 'http://localhost:8080/approvals/apr_01JB8'

function draw(card: AdaptiveCard): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <AdaptiveCardView card={card} onOpen={() => undefined} />
    </MemoryRouter>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

describe('the approval card', () => {
  it('draws every line the platform sent, in order', () => {
    expect(text(draw(WAITING))).toBe(
      [
        'Software watchlist wants to make 1 change. Nothing is written until an Approver says yes.',
        '• Create Jira ticket in MOCK: Upgrade LangGraph from 1.2.14 to 1.2.16',
        'What the agents found',
        'LangGraph has a new release: 1.2.16.',
        'Who can decide',
        'Any Approver',
        'Alice can’t decide, because this run is their own work.',
        'Open in AI Workflow Builder',
      ].join(' '),
    )
  })

  it('has one button, a link that opens the approval page at its absolute address', () => {
    const html = draw(WAITING)
    expect(html).not.toContain('<button')
    const links = [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [m[1], text(m[2] ?? '')])
    expect(links).toEqual([[OPEN_URL, 'Open in AI Workflow Builder']])
  })

  it('shows who decided on top once the request is decided, in the outcome’s colour', () => {
    const html = draw(DECIDED)
    expect(text(html).startsWith('Approved by Bob Software watchlist wants to make 1 change.')).toBe(true)
    expect(html).toMatch(/<strong[^>]*data-color="good"[^>]*>Approved by Bob<\/strong>/)
  })

  it('shows text the platform did not write exactly as written, never as markup', () => {
    const card: AdaptiveCard = {
      ...WAITING,
      body: [{ type: 'RichTextBlock', inlines: [{ type: 'TextRun', text: '**Approve now** <img src=x onerror=alert(1)> [here](https://evil.example)' }] }],
    }
    const html = draw(card)
    expect(html).not.toContain('<img')
    expect(html).not.toContain('<strong')
    expect(html).toContain('**Approve now** &lt;img src=x onerror=alert(1)&gt; [here](https://evil.example)')
  })

  it('draws only links to a web address', () => {
    const card: AdaptiveCard = { ...WAITING, actions: [{ type: 'Action.OpenUrl', title: 'Open', url: 'javascript:alert(1)' }] }
    expect(draw(card)).not.toContain('javascript:')
  })
})

describe('where the card’s link goes in the practice copy', () => {
  it('stays in the app when the link is to the app itself', () => {
    expect(inAppPath(OPEN_URL, 'http://localhost:8080')).toBe('/approvals/apr_01JB8')
    expect(inAppPath('http://localhost:8080/approvals/apr_1?x=1#d', 'http://localhost:8080')).toBe('/approvals/apr_1?x=1#d')
  })

  it('leaves the app for any other address, as Teams would', () => {
    expect(inAppPath(OPEN_URL, 'https://portal.example.test')).toBeNull()
    expect(inAppPath('not a url', 'http://localhost:8080')).toBeNull()
  })
})
