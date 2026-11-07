import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import offline from '../../../../contracts/fixtures/planner/answer.offline.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import { ApiProvider } from '../../api/context'
import { FlagsProvider } from '../../api/flags'
import { createDevSession } from '../../api/session'
import type { CantReply, OfflineReply, PartReply, PlannerReply, SetupCardReply } from '../../api/types'
import { Answer, type Page } from './AnswerCards'

const PAGE: Page = { ask: () => undefined, edit: () => undefined }

function draw(reply: PlannerReply, { oldNewWorkflow = false, typed = 'Every Friday, sum up the tickets we closed this week' } = {}): string {
  const queryClient = new QueryClient()
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <FlagsProvider config={{ newWorkflowSteps: oldNewWorkflow }}>
          <MemoryRouter>
            <Answer reply={reply} typed={typed} page={PAGE} />
          </MemoryRouter>
        </FlagsProvider>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))

describe('a set-up card before setting up from the card is built', () => {
  it('offers the old New workflow while its flag is on, handing it the words', () => {
    const html = draw(setupCard as SetupCardReply, { oldNewWorkflow: true })
    expect(buttons(html)).toContain('Set it up in New workflow')
    expect(html).toContain('href="/new"')
  })

  it('shows no dead button with the flag off, and says it can’t be turned on from here yet', () => {
    const html = draw(setupCard as SetupCardReply)
    expect(buttons(html)).not.toContain('Set it up in New workflow')
    expect(text(html)).toContain('Turning this on from Home isn’t built yet, so nothing was saved.')
  })

  it('tags the Planner’s guess, its name included, and gives each part a label', () => {
    const html = text(draw(setupCard as SetupCardReply))
    expect(html).toContain('Weekly summary of closed tickets Filled in by me')
    expect(html).toContain('Looks for Tickets closed this week in MOCK Filled in by me')
    expect(html).toContain('You already have a workflow with this name.')
  })
})

describe('an answer that is partly a can’t', () => {
  it('lists what it can’t do and the part it can, with Ask the team beside it', () => {
    const html = draw(part as PartReply, { oldNewWorkflow: true })
    expect(text(html)).toContain('What I can’t do yet')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Set up the part I can do in New workflow', 'Ask the team']))
  })

  it('shows a can’t row’s note when its text is empty', () => {
    const empty: PartReply = { ...(part as PartReply), cant: [{ kind: 'do', text: '', note: 'Email isn’t connected.', needs: 'new_system', system: 'email' }] }
    expect(text(draw(empty))).toContain('Email isn’t connected.')
  })

  it('shows the alternative under its own heading, with Ask the team first when there is no alternative', () => {
    const html = draw(cant as CantReply, { oldNewWorkflow: true })
    expect(text(html)).toContain('What I can do instead')
    expect(buttons(html)).toContain('Set up the alternative in New workflow')
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
    expect(draw(refused as PlannerReply, { oldNewWorkflow: true })).not.toContain('href="/new"')
  })
})

describe('the offline answer', () => {
  it('offers Connect a model and the watchlist, and the old New workflow for the other starters only while it is on', () => {
    const reply = offline as OfflineReply
    const off = draw(reply)
    expect(buttons(off)).toEqual(['Open the Software watchlist', 'Connect a model'])
    const on = draw(reply, { oldNewWorkflow: true })
    expect(buttons(on).filter((name) => name === 'Set it up in New workflow')).toHaveLength(2)
  })
})
