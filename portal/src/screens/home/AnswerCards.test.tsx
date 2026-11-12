import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import checkLeftover from '../../../../contracts/fixtures/planner/answer.check_workflows.leftover.json'
import ownTime from '../../../../contracts/fixtures/planner/answer.watchlist.own_time.json'
import offline from '../../../../contracts/fixtures/planner/answer.offline.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import setupClash from '../../../../contracts/fixtures/planner/answer.setup_card.clash.json'
import setupCross from '../../../../contracts/fixtures/planner/answer.setup_card.cross.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { CantReply, OfflineReply, PartReply, PartView, PlannerReply, QuestionReply, SetupCardReply, WatchlistReply } from '../../api/types'
import { Answer, type Page } from './AnswerCards'
import { sayOf } from './answers'
import { Leftovers } from './PartsList'

const PAGE: Page = { ask: () => undefined, edit: () => undefined }

function draw(reply: PlannerReply, { typed = 'Every Friday, sum up the tickets we closed this week', leftovers = false } = {}): string {
  const queryClient = new QueryClient()
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>{leftovers ? <Leftovers reply={reply} /> : <Answer reply={reply} typed={typed} page={PAGE} />}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))

const cardOf = (html: string) => /<section\b[^>]*data-card=[\s\S]*?<\/section>/.exec(html)?.[0] ?? ''

describe('a set-up card', () => {
  it('is the card itself, with Turn it on and the footer line, and no hand-off to another screen', () => {
    const html = draw(setupCard as SetupCardReply)
    expect(buttons(html)).toContain('Turn it on')
    expect(html).not.toContain('href="/new"')
    expect(text(html)).not.toContain('isn’t built yet')
  })

  it('tags the Planner’s guess, its name included, and lists each part with its mark, the destination last', () => {
    const html = text(draw(setupCard as SetupCardReply))
    expect(html).toContain('Weekly summary of closed tickets Filled in by me')
    expect(html).toContain('Will do: Which tickets tickets closed this week in MOCK')
    expect(html).toContain('You said “the tickets we closed”. I read that as MOCK, the project on your list.')
    expect(html).toContain('Will do: What it does sum them up in one new ticket')
    expect(html).toContain('Will do: Where it goes in the MOCK project')
    expect(html).toContain('one new Jira ticket , filled in by me, written after a yes. Change after a yes')
    expect(html).toContain('You already have a workflow with this name.')
    expect(html).not.toContain('What will happen')
  })

  it('never guesses a time: with no time said, it asks one question, the time, with choices and Another time', () => {
    const html = draw(setupCard as SetupCardReply)
    expect(html.match(/data-mark="ask"/g)).toHaveLength(1)
    expect(text(html)).toContain('Question: When What time should it run?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['8:00', '9:00', '13:00', '17:00', 'Another time']))
    expect(text(html)).toMatch(/\d choices? left: when it runs/)
  })
})

describe('PartsList on a set-up card', () => {
  it('quotes a clause the Planner didn’t follow with a cross, and the button sets up the part it can', () => {
    const html = draw(setupCross as SetupCardReply)
    expect(text(html)).toContain('Can’t do: “colour them by team” I didn’t follow this part.')
    expect(text(html)).toContain('Will do: When Every Friday at 17:00, Singapore time')
    expect(buttons(html)).toContain('Set up the part I can')
    expect(buttons(html)).not.toContain('Turn it on')
    expect(text(html)).not.toContain('Nothing is unclear')
  })

  it('asks which of two days, never picking the first, with the clash marked as a cross', () => {
    const html = draw(setupClash as SetupCardReply, { typed: 'Every Monday and Friday at 9am, sum up the closed tickets in MOCK' })
    expect(text(html)).toContain('Question: When Monday or Friday?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Monday', 'Friday']))
    expect(buttons(html)).not.toContain('Another time')
    expect(text(html)).toContain('Can’t do: “Monday and Friday” I can only set one day.')
  })

  it('marks every mark in words for a screen reader, never by colour alone', () => {
    const html = draw(setupCross as SetupCardReply)
    for (const mark of ['ok', 'no']) expect(html).toContain(`data-mark="${mark}"`)
    expect(html.match(/class="visually-hidden">(?:Will do|Can’t do|Question|Question for later): </g)?.length).toBe(html.match(/data-mark=/g)?.length)
  })
})

describe('a clause the Planner didn’t follow, sent as a can’t with the rest to set up', () => {
  const NOT_FOLLOWED: PartView = { text: 'Colour them by team', mark: 'cant', reason: 'not_followed', note: null, choices: [] }
  const reply: CantReply = {
    answer: 'cant',
    cant: [{ kind: 'look_for', text: 'Colour them by team', note: 'I didn’t follow this part.', needs: null, system: null }],
    alternative: { ...(setupCard as SetupCardReply), parts: [] },
    parts: [{ text: 'Every Friday', mark: 'will_do', reason: null, note: null, choices: [] }, NOT_FOLLOWED],
  }

  it('is one set-up card with the clause crossed, never a can’t card, and keeps it as left out', () => {
    const html = draw(reply)
    expect(text(html)).not.toContain('What I can’t do yet')
    expect(text(html)).not.toContain('What I can do instead')
    expect(text(cardOf(html))).toContain('Can’t do: “Colour them by team” I didn’t follow this part.')
    expect(buttons(html)).toContain('Set up the part I can')
    expect(sayOf(reply)).toBe('Here’s what I understood. I can’t do every part of it.')
    expect(draw(reply, { leftovers: true })).toBe('')
  })

  it('is the part it can do when what it can’t do is a filter or a tool the team could add: a cross with Ask the team on one card', () => {
    const note = 'I can’t search by this yet.'
    const filter: CantReply = {
      ...reply,
      cant: [{ kind: 'look_for', text: 'mention VPN', note, needs: 'new_tool', system: 'Jira' }],
      parts: [{ text: 'mention VPN', mark: 'cant', reason: 'cant_do', note, choices: [] }],
    }
    const html = draw(filter)
    expect(text(html)).not.toContain('What I can’t do yet')
    expect(text(cardOf(html))).toContain('Can’t do: “mention VPN” I can’t search by this yet. Ask the team')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Set up the part I can', 'Ask the team']))
  })

  it('keeps the question of how many days on the card a can’t sets up, so it is asked and never “Nothing is unclear”', () => {
    // “Every Friday, list the stale tickets in MOCK and email me”, as the runtime marks it.
    const emailRow = { kind: 'do', text: 'email me', note: 'I can’t send email.', needs: 'new_system', system: 'email' } as const
    const stale: CantReply = {
      answer: 'cant',
      cant: [emailRow],
      alternative: { ...(setupCard as SetupCardReply), parts: [] },
      parts: [
        { text: 'Every Friday', mark: 'will_do', reason: null, note: null, choices: [] },
        { text: 'list the stale tickets in MOCK', mark: 'question', reason: 'how_many_days', note: null, choices: [] },
        { text: 'email me', mark: 'cant', reason: 'cant_do', note: 'I can’t send email.', choices: [] },
      ],
    }
    const card = text(cardOf(draw(stale)))
    expect(card).toContain('“list the stale tickets in MOCK”')
    expect(card).toMatch(/choices left: .*how many days/)
    expect(card).not.toContain('Nothing is unclear')
    expect(card, 'the can’t stays on its own card').not.toContain('“email me”')
    const onCard: CantReply = { ...stale, cant: [{ ...emailRow, needs: 'new_tool' }] }
    expect(text(cardOf(draw(onCard)))).toMatch(/choices left: .*how many days/)
  })

  it('still names a real can’t on its own card, with the clause crossed on the card it sets up instead', () => {
    const mixed: CantReply = { ...(cant as CantReply), parts: [...(cant as CantReply).parts, NOT_FOLLOWED] }
    const html = draw(mixed)
    expect(text(html)).toContain('What I can’t do yet')
    expect(text(html)).toContain('What I can do instead')
    expect(text(cardOf(html))).toContain('“Colour them by team” I didn’t follow this part.')
    expect(text(cardOf(html))).not.toMatch(/email/i)
  })
})

describe('a can’t answer with nothing it can’t do', () => {
  it('draws no can’t card, since the clauses it didn’t follow are drawn above', () => {
    const notFollowed: PartView = { text: 'only the major releases', mark: 'cant', reason: 'not_followed', note: null, choices: [] }
    const bare: CantReply = { answer: 'cant', cant: [{ kind: 'look_for', text: 'only the major releases', note: 'I didn’t follow this part.', needs: null, system: null }], alternative: null, parts: [notFollowed] }
    expect(draw(bare)).toBe('')
    expect(text(draw(bare, { leftovers: true }))).toBe('Can’t do: “only the major releases” I didn’t follow this part.')
  })
})

describe('the clauses an answer didn’t read', () => {
  it('are drawn above a state answer, to ask on their own', () => {
    expect(text(draw(checkLeftover as PlannerReply, { leftovers: true }))).toBe('Can’t do: “every Friday sum up the closed tickets” Ask this on its own, and I’ll answer it.')
  })

  it('give a watch request’s own time its reason', () => {
    expect(text(draw(ownTime as WatchlistReply, { leftovers: true }))).toBe(
      'Can’t do: “every day at 8am” The Software watchlist checks all your software together, on one schedule. I can’t give one software its own time yet.',
    )
  })

  it('never repeat what a can’t answer’s card already says, and a set-up card marks its own', () => {
    expect(draw(cant as CantReply, { leftovers: true })).toBe('')
    expect(draw(setupCross as SetupCardReply, { leftovers: true })).toBe('')
  })
})

describe('an answer that is partly a can’t', () => {
  it('crosses what it can’t do on the card, with the registry’s reason and Ask the team, and sets up the part it can', () => {
    const html = draw(part as PartReply)
    expect(text(cardOf(html))).toMatch(/Can’t do: “email it to the team” I can.t email it to the team\./)
    expect(buttons(html)).toEqual(expect.arrayContaining(['Set up the part I can', 'Ask the team']))
    const rows = text(cardOf(html)).split('Can’t do:')[0]?.split('Question: When')[1] ?? ''
    expect(rows, 'the ticked rows hold only the part it can do').toContain('sum them up')
    expect(rows).not.toMatch(/email/i)
  })

  it('keeps a can’t row as a cross even when no part names it, its note standing in for empty text', () => {
    const empty: PartReply = { ...(part as PartReply), parts: [], cant: [{ kind: 'do', text: '', note: 'Email isn’t connected.', needs: 'new_system', system: 'email' }] }
    expect(text(draw(empty))).toContain('Can’t do: “Email isn’t connected.”')
  })

  it('shows the alternative under its own heading, with Ask the team first when there is no alternative', () => {
    const html = draw(cant as CantReply)
    expect(text(html)).toContain('What I can do instead')
    expect(buttons(html)).toContain('Turn it on')
    const bare = draw({ ...(cant as CantReply), alternative: null })
    expect(bare).not.toContain('What I can do instead')
    expect(buttons(bare)).toEqual(['Ask the team'])
  })
})

describe('a refusal', () => {
  it('states the rule, offers the rest back to the Planner and a way to say it another way', () => {
    const html = draw(refused as PlannerReply)
    expect(text(html)).toContain('Nobody approves their own work')
    expect(text(html)).toContain('If you only meant that you don’t need to look at it yourself, say it another way.')
    expect(buttons(html)).toEqual(['Set it up with a yes', 'Say it another way'])
  })

  it('has only the way to say it another way when nothing was left after the refused part', () => {
    expect(buttons(draw({ ...(refused as PlannerReply), rest: '' } as PlannerReply))).toEqual(['Say it another way'])
  })

  it('never links straight to a set-up, because the rest can hold more than the person meant', () => {
    expect(draw(refused as PlannerReply)).not.toContain('href="/new"')
  })
})

describe('the offline answer', () => {
  it('offers Connect a model and the watchlist, and nothing else to click', () => {
    expect(buttons(draw(offline as OfflineReply))).toEqual(['Open the Software watchlist', 'Connect a model'])
  })
})

describe('the answer to a question about the person’s own data', () => {
  const links = (html: string) => [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => [m[1], text(m[2] ?? '')])

  it('shows the sections it looked at as links, and nothing else to click', () => {
    const html = draw(question as QuestionReply)
    expect(text(html)).toBe('Looked at Software')
    expect(links(html)).toEqual([['/software', 'Software']])
    expect(buttons(html)).toEqual(['Software'])
  })

  it('links each section to the screen it was read from, Needs you to the Workflows page, where Needs you leads', () => {
    const html = draw({ ...(question as QuestionReply), looked_at: ['watchlist', 'workflows', 'needs_you'] })
    expect(text(html)).toBe('Looked at Software Workflows Needs you')
    expect(links(html)).toEqual([
      ['/software', 'Software'],
      ['/workflows', 'Workflows'],
      ['/workflows', 'Needs you'],
    ])
  })

  it('has no Looked at line for the fixed fallback, which looked at nothing', () => {
    expect(draw({ ...(question as QuestionReply), looked_at: [] })).toBe('')
  })

  it('draws plain links, so the keyboard reaches each one, with no tab stop removed and no motion', () => {
    const html = draw({ ...(question as QuestionReply), looked_at: ['watchlist', 'workflows', 'needs_you'] })
    expect(html).not.toContain('tabindex')
    expect(html).not.toContain('aria-hidden')
    expect(html).not.toContain('animation')
  })
})
