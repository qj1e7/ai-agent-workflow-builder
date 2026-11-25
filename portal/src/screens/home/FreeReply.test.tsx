import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Children, isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import ownTime from '../../../../contracts/fixtures/planner/answer.watchlist.own_time.json'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { FreeReply, Me, PartView, PlannerReply, UseCaseView, WatchlistReply, WatchlistView } from '../../api/types'
import { Answer, DidntFollowCard, ReplyCant, ReplyChoices, SayItAnotherWay, type Page } from './AnswerCards'
import { AskTheTeam } from './AskTheTeam'
import { AskAboutThis } from './CrossNext'
import { sayOf, wordsOnly } from './answers'
import { Leftovers } from './PartsList'
import { AskPlanner } from './primary'
import { Thread } from './Thread'
import { EMPTY, threadReducer } from './threadState'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }

const free = (form: FreeReply['form'], over: Partial<FreeReply> = {}): FreeReply => ({ trace_id: null, answer: 'reply', form, text: 'Some words.', choices: [], offer: null, looked_at: [], about: [], software: null, parts: [], ...over })
const crossed = (text: string, reason: PartView['reason']): PartView => ({ text, mark: 'cant', reason, note: null, choices: [] })
const NO_PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }

function draw(node: ReactNode, me: Me = ALICE, watched?: WatchlistView, useCases?: UseCaseView[]): string {
  const session = createDevSession(null)
  const client = new QueryClient()
  client.setQueryData(['me', session.cacheScope()], me)
  if (watched) client.setQueryData(['watchlist', session.cacheScope()], watched)
  if (useCases) client.setQueryData(['use-cases', session.cacheScope()], useCases)
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>{node}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const inThread = (reply: PlannerReply, me: Me = ALICE) =>
  draw(<Thread thread={threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'hmm', chat: 'c1' }), { type: 'answered', reply, typed: 'hmm' })} now={new Date('2026-11-15T10:00:00+08:00')} page={NO_PAGE} />, me)

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replaceAll('&quot;', '"').replace(/\s+/g, ' ').trim()
const said = (html: string) => /<li[^>]*data-answer[^>]*>([\s\S]*)<\/li>/.exec(html)?.[1] ?? ''
const press = (element: ReactNode) => (element as ReactElement<{ onClick: () => void }>).props.onClick()
const clickables = (element: ReactElement<{ children?: ReactNode }>) => Children.toArray(element.props.children).filter(isValidElement) as ReactElement<{ onClick: () => void; children: ReactNode }>[]

describe('a free reply, drawn as the Planner’s own message', () => {
  it('is words with the Planner’s name, and its sentence is the one the polite region reads', () => {
    const reply = free('answer', { text: 'Type what you want done in the box.' })
    expect(sayOf(reply)).toBe('Type what you want done in the box.')
    expect(wordsOnly(reply, 'operator')).toBe(true)
    const html = inThread(reply)
    expect(said(html)).toMatch(/>Planner<span class="visually-hidden">:<\/span><\/span>/)
    expect(text(said(html))).toContain('Type what you want done in the box.')
  })

  it('shows Markdown and HTML as the plain characters they are', () => {
    const html = inThread(free('answer', { text: 'Use **bold** and <b>this</b> <script>x()</script>' }))
    expect(html).toContain('Use **bold** and &lt;b&gt;this&lt;/b&gt; &lt;script&gt;x()&lt;/script&gt;')
    expect(html).not.toContain('<b>this</b>')
    expect(html).not.toContain('<script>')
  })

  it('links to what it looked at, as a question answer does', () => {
    const html = draw(<Answer reply={free('answer', { looked_at: ['watchlist', 'needs_you'] })} typed="x" page={NO_PAGE} />)
    expect(html).toMatch(/<a [^>]*href="\/software"[^>]*>Software<\/a>/)
    expect(html).toMatch(/<a [^>]*href="\/workflows"[^>]*>Needs you<\/a>/)
  })

  it('draws a clarifying question’s choices as real buttons that send their own words', () => {
    const reply = free('clarify', { text: 'Which one?', choices: ['New releases of some software', 'Jira tickets every week'] })
    const html = draw(<Answer reply={reply} typed="x" page={NO_PAGE} />)
    const chips = [...html.matchAll(/<button type="button" class="[^"]*chip[^"]*"[^>]*>([^<]*)<\/button>/g)].map((m) => m[1])
    expect(chips).toEqual(['New releases of some software', 'Jira tickets every week'])
    const ask = vi.fn()
    const row = clickables(ReplyChoices({ choices: reply.choices, ask }))
    expect(row).toHaveLength(2)
    press(row[1])
    expect(ask).toHaveBeenCalledExactlyOnceWith('Jira tickets every week')
  })

  it('gives a can’t with an offer one button, which says the request it sends', () => {
    const reply = free('cant', { text: 'I can’t send email yet.', offer: { capability: 'jira.create', request: 'Every Monday at 9am, list new bugs in one Jira ticket' } })
    const html = draw(<Answer reply={reply} typed="email my manager" page={NO_PAGE} />)
    expect([...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))).toEqual(['Try “Every Monday at 9am, list new bugs in one Jira ticket”'])
    const ask = vi.fn()
    press(ReplyCant({ reply, typed: 'email my manager', ask, variant: 'primary' }))
    expect(ask).toHaveBeenCalledExactlyOnceWith('Every Monday at 9am, list new bugs in one Jira ticket')
  })

  it('gives a can’t with no offer Ask the team, starting from what they asked', () => {
    const reply = free('cant', { text: 'I can’t do that yet.' })
    const button = ReplyCant({ reply, typed: 'email my manager', ask: () => undefined, variant: 'primary' }) as ReactElement<{ starter: string }>
    expect(button.type).toBe(AskTheTeam)
    expect(button.props.starter).toBe('I asked the Planner for: email my manager')
    expect(text(draw(<Answer reply={reply} typed="email my manager" page={NO_PAGE} />))).toContain('Ask the team')
  })

  it('draws the sorry face for a can’t and for the fallback, and the idle face for an answer', () => {
    const face = (reply: PlannerReply) => /<svg\b[\s\S]*?<\/svg>/.exec(said(inThread(reply)))?.[0] ?? ''
    const idle = face(free('answer'))
    expect(idle).not.toBe('')
    expect(face(free('clarify', { choices: ['a', 'b'] }))).toBe(idle)
    expect(face(free('cant'))).not.toBe(idle)
    expect(face({ trace_id: null, answer: 'didnt_follow', parts: [] })).not.toBe(idle)
    expect(face(free('cant'))).toBe(face({ trace_id: null, answer: 'didnt_follow', parts: [] }))
  })
})

describe('what a free reply names, drawn from live data', () => {
  const NOW = new Date('2026-11-15T10:00:00+08:00')
  const WATCHED = statuses as WatchlistView
  const [FIRST] = WATCHED.software
  if (!FIRST) throw new Error('the statuses fixture has rows')
  const FLOW = { ...(agentUseCase as UseCaseView), use_case_id: 'uc_release', name: 'Release check' }
  const rows = (html: string) => [...html.matchAll(/data-(?:software|workflow)-id="([^"]+)"/g)].map((m) => m[1])
  const drawThread = (reply: FreeReply, me: Me = ALICE) =>
    draw(<Thread thread={threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'hmm', chat: 'c1' }), { type: 'answered', reply, typed: 'hmm' })} now={NOW} page={NO_PAGE} />, me, WATCHED, [FLOW])

  it('draws a software row and a workflow row, each from its own list, whatever the form', () => {
    for (const form of ['answer', 'clarify', 'cant'] as const) {
      const about = [{ section: 'watchlist' as const, name: FIRST.name.toUpperCase() }, { section: 'workflows' as const, name: 'release check' }]
      const html = drawThread(free(form, { about, choices: form === 'clarify' ? ['a', 'b'] : [] }))
      expect(rows(html), form).toEqual([FIRST.id, 'uc_release'])
      expect(text(html)).toContain(FIRST.name)
      expect(text(html)).toContain('Release check')
    }
  })

  it('shows the same rows to an Approver, with no button that changes anything', () => {
    const html = drawThread(free('answer', { about: [{ section: 'watchlist', name: FIRST.name }] }), BOB)
    expect(rows(html)).toEqual([FIRST.id])
    expect(html).not.toContain('Stop watching')
  })

  it('draws nothing for a name no live list holds, and nothing for a reply that names none', () => {
    const html = drawThread(free('answer', { about: [{ section: 'watchlist', name: 'Nothing Here' }, { section: 'workflows', name: 'Nor Here' }] }))
    expect(rows(html)).toEqual([])
    expect(html).not.toContain('On your watchlist')
    expect(rows(drawThread(free('answer')))).toEqual([])
  })

  it('looks a name up in its own section only', () => {
    const html = drawThread(free('answer', { about: [{ section: 'workflows', name: FIRST.name }] }))
    expect(rows(html)).toEqual([])
  })
})

describe('the fallback card', () => {
  it('says I didn’t follow that, with the role’s one line and a way to say it another way', () => {
    const operator = draw(<DidntFollowCard typed="blorp" page={NO_PAGE} />)
    expect(text(operator)).toBe('I didn’t follow that I can watch software releases, fix stopped runs and change your workflows. Say it another way')
    const approver = draw(<DidntFollowCard typed="blorp" page={NO_PAGE} />, BOB)
    expect(text(approver)).toBe('I didn’t follow that I can show what needs your approval, and your past decisions. Say it another way')
  })

  it('puts their own words back in the box', () => {
    const edit = vi.fn()
    press(SayItAnotherWay({ typed: 'blorp', page: { ...NO_PAGE, edit }, variant: 'primary' }))
    expect(edit).toHaveBeenCalledExactlyOnceWith('blorp')
    const html = draw(<Answer reply={{ trace_id: null, answer: 'didnt_follow', parts: [crossed('blorp', 'not_followed')] }} typed="blorp" page={{ ...NO_PAGE, edit }} />)
    expect(html).toContain('Say it another way')
    expect(html).not.toContain('Ask about this')
  })
})

describe('a cross’s next step', () => {
  const notFollowed = crossed('flibber the wotsit', 'not_followed')
  const watchReply: WatchlistReply = { ...(ownTime as WatchlistReply) }

  it('asks a clause it didn’t follow, and one to ask on its own, as that part’s own words', () => {
    const reply: PlannerReply = { trace_id: null, answer: 'check_workflows', use_case_id: null, parts: [notFollowed, crossed('what is Jira?', 'ask_on_its_own')] }
    const html = draw(<AskPlanner.Provider value={() => undefined}><Leftovers reply={reply} /></AskPlanner.Provider>)
    expect(html.match(/<button type="button"[^>]*>Ask about this<\/button>/g)).toHaveLength(2)
    const ask = vi.fn()
    press(AskAboutThis({ text: 'what is Jira?', ask }))
    expect(ask).toHaveBeenCalledExactlyOnceWith('what is Jira?')
  })

  it('draws no button that would do nothing when there is nowhere to send the question', () => {
    const reply = { answer: 'check_workflows', use_case_id: null, parts: [notFollowed] } as PlannerReply
    expect(draw(<Leftovers reply={reply} />)).not.toContain('Ask about this')
  })

  it('reaches the Planner from a cross in the thread', () => {
    const reply = { answer: 'check_workflows', use_case_id: null, parts: [notFollowed] } as PlannerReply
    expect(inThread(reply)).toContain('Ask about this')
  })

  it('leaves the cross on a watch request’s own time to the Software watchlist’s offer', () => {
    const html = draw(<Leftovers reply={watchReply} />, ALICE, statuses as WatchlistView)
    expect(html).not.toContain('Ask about this')
    expect(html).not.toContain('Change when the watchlist checks')
  })
})
