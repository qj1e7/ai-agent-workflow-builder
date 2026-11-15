import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Children, isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import ownTime from '../../../../contracts/fixtures/planner/answer.watchlist.own_time.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { FreeReply, Me, PartView, PlannerReply, WatchlistReply, WatchlistView } from '../../api/types'
import { Answer, DidntFollowCard, ReplyCant, ReplyChoices, SayItAnotherWay, type Page } from './AnswerCards'
import { AskTheTeam } from './AskTheTeam'
import { AskAboutThis, ChangeWhen } from './CrossNext'
import { sayOf, wordsOnly } from './answers'
import { ScheduleEditor } from '../software/Schedule'
import { Leftovers } from './PartsList'
import { AskPlanner } from './primary'
import { Thread } from './Thread'
import { EMPTY, threadReducer } from './threadState'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }

const free = (form: FreeReply['form'], over: Partial<FreeReply> = {}): FreeReply => ({ answer: 'reply', form, text: 'Some words.', choices: [], offer: null, looked_at: [], parts: [], ...over })
const crossed = (text: string, reason: PartView['reason']): PartView => ({ text, mark: 'cant', reason, note: null, choices: [] })
const NO_PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }

function draw(node: ReactNode, me: Me = ALICE, watched?: WatchlistView): string {
  const session = createDevSession(null)
  const client = new QueryClient()
  client.setQueryData(['me', session.cacheScope()], me)
  if (watched) client.setQueryData(['watchlist', session.cacheScope()], watched)
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>{node}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const inThread = (reply: PlannerReply, me: Me = ALICE) =>
  draw(<Thread thread={threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'hmm' }), { type: 'answered', reply, typed: 'hmm' })} now={new Date('2026-11-15T10:00:00+08:00')} page={NO_PAGE} />, me)

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

  it('gives a can’t with no offer Ask the team, starting from what she asked', () => {
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
    expect(face({ answer: 'didnt_follow', parts: [] })).not.toBe(idle)
    expect(face(free('cant'))).toBe(face({ answer: 'didnt_follow', parts: [] }))
  })
})

describe('the fallback card', () => {
  it('says I didn’t follow that, with the role’s one line and a way to say it another way', () => {
    const operator = draw(<DidntFollowCard typed="blorp" page={NO_PAGE} />)
    expect(text(operator)).toBe('I didn’t follow that I can watch software releases, fix stopped runs and change your workflows. Say it another way')
    const approver = draw(<DidntFollowCard typed="blorp" page={NO_PAGE} />, BOB)
    expect(text(approver)).toBe('I didn’t follow that I can show what waits for your yes, and your past decisions. Say it another way')
  })

  it('puts her own words back in the box', () => {
    const edit = vi.fn()
    press(SayItAnotherWay({ typed: 'blorp', page: { ...NO_PAGE, edit }, variant: 'primary' }))
    expect(edit).toHaveBeenCalledExactlyOnceWith('blorp')
    const html = draw(<Answer reply={{ answer: 'didnt_follow', parts: [crossed('blorp', 'not_followed')] }} typed="blorp" page={{ ...NO_PAGE, edit }} />)
    expect(html).toContain('Say it another way')
    expect(html).not.toContain('Ask about this')
  })
})

describe('a cross’s next step', () => {
  const notFollowed = crossed('flibber the wotsit', 'not_followed')
  const watchReply: WatchlistReply = { ...(ownTime as WatchlistReply) }

  it('asks a clause it didn’t follow, and one to ask on its own, as that part’s own words', () => {
    const reply: PlannerReply = { answer: 'check_workflows', use_case_id: null, parts: [notFollowed, crossed('what is Jira?', 'ask_on_its_own')] }
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

  it('lets an Operator change when the watchlist checks, from the cross on its own time', () => {
    const html = draw(<Leftovers reply={watchReply} />, ALICE, statuses as WatchlistView)
    expect(html).toMatch(/<button type="button"[^>]*>Change when the watchlist checks<\/button>/)
    expect(html).not.toContain('Save schedule')
  })

  it('swaps the button for the watchlist’s own schedule form once opened, and the button opens it', () => {
    const watched = statuses as WatchlistView
    const form = <ScheduleEditor schedule={watched.schedule} version={watched.version} onDone={() => undefined} onStale={() => undefined} />
    const onOpen = vi.fn()
    const closed = draw(<ChangeWhen editing={false} onOpen={onOpen} opener={null} problem={null} editor={form} />)
    expect(closed).toContain('Change when the watchlist checks')
    expect(closed).not.toContain('Save schedule')
    const opened = draw(<ChangeWhen editing onOpen={onOpen} opener={null} problem={null} editor={form} />)
    expect(opened).toContain('Save schedule')
    expect(opened).not.toContain('Change when the watchlist checks')
    press((ChangeWhen({ editing: false, onOpen, opener: null, editor: form, problem: null }) as ReactElement<{ children: ReactNode[] }>).props.children[0])
    expect(onOpen).toHaveBeenCalledOnce()
  })

  it('says so, as an alert, when the watchlist changed since she opened the form', () => {
    expect(draw(<ChangeWhen editing={false} onOpen={() => undefined} opener={null} problem="Changed since you opened it. Nothing was saved." editor={null} />)).toContain('role="alert">Changed since you opened it. Nothing was saved.')
  })

  it('offers an Approver no way to change the watchlist’s time', () => {
    const html = draw(<Leftovers reply={watchReply} />, BOB, statuses as WatchlistView)
    expect(html).not.toContain('Change when the watchlist checks')
    expect(html).not.toContain('Save schedule')
  })
})
