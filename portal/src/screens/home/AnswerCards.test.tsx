import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import checkLeftover from '../../../../contracts/fixtures/planner/answer.check_workflows.leftover.json'
import ownTime from '../../../../contracts/fixtures/planner/answer.watchlist.own_time.json'
import statuses from '../../../../contracts/fixtures/watchlist/statuses.json'
import offline from '../../../../contracts/fixtures/planner/answer.offline.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import setupClash from '../../../../contracts/fixtures/planner/answer.setup_card.clash.json'
import setupCross from '../../../../contracts/fixtures/planner/answer.setup_card.cross.json'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import stoppedUseCase from '../../../../contracts/fixtures/builder/use-case.stopped.json'
import decisionsOfBob from '../../../../contracts/fixtures/approvals/decisions.bob.json'
import bobApproval from '../../../../contracts/fixtures/approvals/apr_01JB8.bob.json'
import noDecisions from '../../../../contracts/fixtures/approvals/decisions.none.json'
import people from '../../../../contracts/fixtures/people/list.json'
import troubleshooting from '../../../../contracts/fixtures/troubleshooting/failure.json'
import operatorsReply from '../../../../contracts/fixtures/planner/answer.operators.json'
import needsMeOperators from '../../../../contracts/fixtures/planner/answer.needs_me.operators.json'
import decidedReply from '../../../../contracts/fixtures/planner/answer.decided.json'
import decidedDeclines from '../../../../contracts/fixtures/planner/answer.decided.declines.json'
import decideReply from '../../../../contracts/fixtures/planner/answer.decide.json'
import decideQuestion from '../../../../contracts/fixtures/planner/answer.decide.question.json'
import pauseReply from '../../../../contracts/fixtures/planner/answer.pause.json'
import pauseChoices from '../../../../contracts/fixtures/planner/answer.pause.choices.json'
import resumeReply from '../../../../contracts/fixtures/planner/answer.resume.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import runFailure from '../../../../contracts/fixtures/runs/failure.json'
import runRejected from '../../../../contracts/fixtures/runs/rejected.json'
import runSuccess from '../../../../contracts/fixtures/runs/success.json'
import runUseCase from '../../../../contracts/fixtures/builder/use-case.json'
import { OpensInPanel } from '../../ui/sidePanel'
import { emptyModel, foldWire, type RunModel } from '../run/runModel'
import { storyOf } from '../run/useRunStory'
import type { ApprovalView, TroubleshootingOut, CantReply, CantRowView, CapabilitiesView, DecisionsView, HomeOut, Me, OfflineReply, PartReply, PartView, PauseReply, PlannerReply, QuestionReply, ResumeReply, SetupCardReply, UseCaseView, WatchlistReply, WatchlistView } from '../../api/types'
import { Answer, type Page } from './AnswerCards'
import { newCardMemory, type CardMemory } from './cardMemory'
import { sayOf, switchedSay, whoOf } from './answers'
import { Leftovers } from './PartsList'
import { RunCardView } from './RunCard'
import { Thread } from './Thread'
import { EMPTY, threadReducer } from './threadState'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
/** The fixture's set-up card, as it is when she has no workflow of that name yet. */
const SETUP: SetupCardReply = { ...(setupCard as SetupCardReply), similar: null }

function draw(reply: PlannerReply, { typed = 'Every Friday, sum up the tickets we closed this week', leftovers = false, registry, watched, useCase }: { typed?: string; leftovers?: boolean; registry?: CapabilitiesView; watched?: WatchlistView; useCase?: UseCaseView } = {}): string {
  const queryClient = new QueryClient()
  if (registry) queryClient.setQueryData(['capabilities', createDevSession(null).cacheScope()], registry)
  if (watched) queryClient.setQueryData(['watchlist', createDevSession(null).cacheScope()], watched)
  if (useCase) queryClient.setQueryData(['use-case', createDevSession(null).cacheScope(), useCase.use_case_id], useCase)
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

const cardOf = (html: string) => /<div\b[^>]*data-card=[\s\S]*?<\/section>/.exec(html)?.[0] ?? ''

describe('the Planner’s short answers, as the chat-first sketch draws them', () => {
  const REGISTRY = capabilities as CapabilitiesView
  const asked = (text: string, mark: PartView['mark'], reason: PartView['reason'] = null): PartView => ({ text, mark, reason, note: null, choices: [] })

  it('lists what I can do in the registry’s short words, with what isn’t built yet in one Not yet line', () => {
    const reply: PlannerReply = { answer: 'abilities', parts: [asked('What can you do', 'will_do')] }
    expect(text(draw(reply, { registry: REGISTRY }))).toBe(
      'What I can do Watch software for new releases Create Jira tickets, after a yes Explain a stopped run, and retry it Change or pause your workflows Not yet: Teams channels, email, Confluence.',
    )
    expect(sayOf(reply)).toBeNull()
  })

  it('never shows a line as working while its connection needs setting up', () => {
    const jiraOff: CapabilitiesView = { ...REGISTRY, capabilities: REGISTRY.capabilities.map((c) => (c.id === 'jira.create' ? { ...c, state: 'needs_setup' as const } : c)) }
    expect(text(draw({ answer: 'abilities', parts: [] }, { registry: jiraOff }))).toContain('Create Jira tickets, after a yes Needs setup')
  })

  it('says it didn’t follow a request it read none of, and what it can do instead', () => {
    const reply: PlannerReply = { answer: 'abilities', parts: [asked('What’s the weather', 'cant', 'not_followed')] }
    expect(text(draw(reply, { registry: REGISTRY }))).toBe('I didn’t follow that I can watch software releases, fix stopped runs and change your workflows.')
    expect(sayOf(reply)).toBeNull()
  })

  const TEAMS: CantRowView = { kind: 'do', text: 'Post the FastAPI news in our Teams channel', note: 'I can\'t post in Teams channels yet.', needs: 'new_system', system: 'Teams', instead: 'Run results show here, in the chat.', unsupported: false }
  const DELETE: CantRowView = { kind: 'do', text: 'delete the MOCK ticket', note: 'I don\'t delete anything in Jira.', needs: 'new_tool', system: 'Jira', instead: 'A Jira admin can do that.', unsupported: true }
  const cantOf = (row: CantRowView): CantReply => ({ answer: 'cant', cant: [row], alternative: null, parts: [{ text: row.text, mark: 'cant', reason: 'cant_do', note: row.note, choices: [] }] })

  it('gives a can’t the registry names one card: the line, what she has instead, and Ask the team', () => {
    const html = draw(cantOf(TEAMS))
    expect(text(html)).toBe('I can\'t post in Teams channels yet Run results show here, in the chat. Ask the team')
    expect(buttons(html)).toEqual(['Ask the team'])
    expect(sayOf(cantOf(TEAMS))).toBeNull()
    expect(draw(cantOf(TEAMS), { leftovers: true }), 'the card already says it').toBe('')
  })

  it('offers no Ask the team for what the platform won’t do', () => {
    const html = draw(cantOf(DELETE))
    expect(text(html)).toBe('I don\'t delete anything in Jira A Jira admin can do that.')
    expect(buttons(html)).toEqual([])
  })

  it('says a pause or a resume in one plain line, and when nothing changed', () => {
    expect(sayOf(pauseReply as PauseReply)).toBe('Paused React release check. It won’t start a new run until you resume it.')
    expect(sayOf(resumeReply as ResumeReply)).toBe('React release check is on again.')
    expect(sayOf({ ...(pauseReply as PauseReply), already: true })).toBe('React release check is already paused.')
    expect(sayOf({ ...(resumeReply as ResumeReply), already: true })).toBe('React release check is already on.')
    expect(draw(pauseReply as PauseReply)).toBe('')
  })

  it('asks which workflow when the words fit a workflow and the watchlist, and says the watchlist’s pause stops every check', () => {
    const reply = pauseChoices as PauseReply
    expect(sayOf(reply)).toBe('Which workflow?')
    expect(buttons(draw(reply))).toEqual(['React release check', 'Software watchlist'])
    expect(text(draw(reply))).toContain('Pausing the Software watchlist stops the checks of every software on it.')
    const workflowsOnly: PauseReply = { ...reply, choices: reply.choices.filter((choice) => !choice.watchlist) }
    expect(text(draw(workflowsOnly))).not.toContain('Software watchlist')
    expect(switchedSay('pause', 'FastAPI release check', false)).toBe('Paused FastAPI release check. It won’t start a new run until you resume it.')
  })

  it('offers five workflows for “pause it”, and links to the rest', () => {
    const many: PauseReply = {
      ...(pauseChoices as PauseReply),
      choices: Array.from({ length: 7 }, (_, at) => ({ use_case_id: `uc_${at}`, name: `Check ${at + 1}`, state: 'on' as const, watchlist: false })),
    }
    expect(buttons(draw(many))).toEqual(['Check 1', 'Check 2', 'Check 3', 'Check 4', 'Check 5', 'and 2 more'])
  })

  it('reads a can’t row from an older platform, with no one-line fields, as a row on the What I can’t do yet card', () => {
    const older = Object.fromEntries(Object.entries(TEAMS).filter(([field]) => field !== 'instead' && field !== 'unsupported'))
    const html = text(draw(cantOf(older as unknown as CantRowView)))
    expect(html).toContain('What I can’t do yet')
    expect(html).toContain('Post the FastAPI news in our Teams channel')
  })

  it('keeps a question asked beside the pause above it, to ask on its own', () => {
    const beside: PauseReply = { ...(pauseReply as PauseReply), parts: [asked('what needs my attention', 'cant', 'ask_on_its_own'), asked('pause the React check', 'will_do')] }
    expect(text(draw(beside, { leftovers: true }))).toContain('“what needs my attention” Ask this on its own, and I’ll answer it.')
  })

  it('names the workflow it can’t find, and changes nothing', () => {
    const missing: PauseReply = { ...(pauseChoices as PauseReply), choices: [], missing: 'the morning check' }
    expect(sayOf(missing)).toBe('You don’t have a workflow called “morning check”.')
    expect(buttons(draw(missing))).toEqual([])
  })
})

describe('a set-up card', () => {
  it('is the card itself, a Draft with Never mind and Set up, and no hand-off to another screen', () => {
    const html = draw(SETUP)
    expect(buttons(html)).toEqual(expect.arrayContaining(['Never mind', 'Set up']))
    expect(buttons(html)).not.toContain('Turn it on')
    expect(text(cardOf(html))).toContain('Weekly summary of closed tickets Draft')
    expect(html).not.toContain('href="/new"')
    expect(text(html)).not.toContain('isn’t built yet')
  })

  it('lists what it understood as Watch, When and Then, each with its mark, and drops the old extras', () => {
    const html = text(draw(SETUP))
    expect(html).toContain('Will do: Watch Tickets closed this week in MOCK')
    expect(html).toContain('You said “the tickets we closed”. I read that as MOCK, the project on your list.')
    expect(html).toContain('Will do: Then Sum them up in one new ticket')
    expect(html).toContain('In the MOCK project')
    expect(html).toContain('After a yes')
    for (const gone of ['Filled in by me', 'Rename', 'How this workflow works', 'What needs a yes']) expect(html).not.toContain(gone)
  })

  it('never guesses a time: with no time said, it asks one question, the time, with choices and Another time', () => {
    const html = draw(SETUP)
    expect(html.match(/data-mark="ask"/g)).toHaveLength(1)
    expect(text(html)).toContain('Question: When Fridays, at what time?')
    expect(buttons(html)).toEqual(expect.arrayContaining(['8:00', '9:00', '13:00', '17:00', 'Another time']))
    expect(text(html)).toMatch(/\d questions? to answer/)
  })

  it('is the already-have card when she has a workflow of that name, with Open it and a way to set up another', () => {
    const html = draw(setupCard as SetupCardReply)
    expect(text(html)).toContain('Weekly summary of closed tickets')
    expect(buttons(html)).toEqual(['Set up another', 'Open it'])
    expect(html).not.toContain('data-card=')
  })

  it('says the workflow she has already watches its software only while it is on', () => {
    const reply = setupCard as SetupCardReply
    const react: UseCaseView = {
      ...(runUseCase as UseCaseView),
      use_case_id: reply.similar?.use_case_id ?? '',
      template: 'agent_cards',
      name: reply.name,
      agents: [{ card_id: 'crd_version_checker', card_version: 1, name: 'Version checker', values: { 'GitHub repository': 'facebook/react', 'Jira project': 'MOCK' } }],
    }
    expect(text(draw(reply, { useCase: react }))).toContain('It already watches facebook/react, every Monday at 9:00.')
    for (const state of ['draft', 'paused'] as const) expect(text(draw(reply, { useCase: { ...react, state, next_run_at: null } })), `a ${state} workflow watches nothing yet`).not.toContain('already')
  })
})

describe('the software card', () => {
  const WATCHED = statuses as WatchlistView
  const ask = (software: string, listed: { name: string; software_id: string } | null): WatchlistReply => ({ answer: 'watchlist', software, word: 'version', already_listed: listed, also: null, parts: [] })

  it('names a watched software with its pill and where it stands, in the watchlist’s own words', () => {
    const html = draw(ask('LangGraph', { name: 'LangGraph', software_id: 'sw_01JBW00000000000000000002' }), { watched: WATCHED })
    expect(text(html)).toContain('LangGraph Newer out You run 1.2.14. Newest is 1.2.16.')
    expect(buttons(html)).toEqual(['Open it'])
    expect(text(html)).not.toContain('Already on the watchlist')
  })

  it('says it doesn’t know the version of software that isn’t on the watchlist, and offers Watch it', () => {
    const html = draw(ask('Kubernetes', null))
    expect(text(html)).toContain('Kubernetes It isn’t on the watchlist, so I don’t know which version you run.')
    expect(buttons(html)).toEqual(['Watch it'])
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
    expect(text(html)).toContain('Can’t do: Monday and Friday. I can only set one day.')
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
    cant: [{ kind: 'look_for', text: 'Colour them by team', note: 'I didn’t follow this part.', needs: null, system: null, instead: null, unsupported: false }],
    alternative: { ...SETUP, parts: [] },
    parts: [{ text: 'Every Friday', mark: 'will_do', reason: null, note: null, choices: [] }, NOT_FOLLOWED],
  }

  it('is one set-up card with the clause crossed, never a can’t card, and keeps it as left out', () => {
    const html = draw(reply)
    expect(text(html)).not.toContain('What I can’t do yet')
    expect(text(html)).not.toContain('What I can do instead')
    expect(text(cardOf(html))).toContain('Can’t do: “Colour them by team” I didn’t follow this part.')
    expect(buttons(html)).toContain('Set up the part I can')
    expect(sayOf(reply)).toBe('Here’s what I understood.')
    expect(draw(reply, { leftovers: true })).toBe('')
  })

  it('is the part it can do when what it can’t do is a filter or a tool the team could add: a cross with Ask the team on one card', () => {
    const note = 'I can’t search by this yet.'
    const filter: CantReply = {
      ...reply,
      cant: [{ kind: 'look_for', text: 'mention VPN', note, needs: 'new_tool', system: 'Jira', instead: null, unsupported: false }],
      parts: [{ text: 'mention VPN', mark: 'cant', reason: 'cant_do', note, choices: [] }],
    }
    const html = draw(filter)
    expect(text(html)).not.toContain('What I can’t do yet')
    expect(text(cardOf(html))).toContain('Can’t do: Mention VPN. I can’t search by this yet. Ask the team')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Set up the part I can', 'Ask the team']))
  })

  it('keeps the question of how many days on the card a can’t sets up, so it is asked and never “Nothing is unclear”', () => {
    // “Every Friday, list the stale tickets in MOCK and email me”, as the runtime marks it.
    const emailRow = { kind: 'do', text: 'email me', note: 'I can’t send email.', needs: 'new_system', system: 'email', instead: null, unsupported: false } as const
    const stale: CantReply = {
      answer: 'cant',
      cant: [emailRow],
      alternative: { ...SETUP, parts: [] },
      parts: [
        { text: 'Every Friday', mark: 'will_do', reason: null, note: null, choices: [] },
        { text: 'list the stale tickets in MOCK', mark: 'question', reason: 'how_many_days', note: null, choices: [] },
        { text: 'email me', mark: 'cant', reason: 'cant_do', note: 'I can’t send email.', choices: [] },
      ],
    }
    const card = text(cardOf(draw(stale)))
    expect(card).toContain('“list the stale tickets in MOCK”')
    expect(card).toMatch(/\d questions? to answer/)
    expect(card, 'the can’t stays on its own card').not.toContain('“email me”')
    const onCard: CantReply = { ...stale, cant: [{ ...emailRow, needs: 'new_tool' }] }
    expect(text(cardOf(draw(onCard)))).toMatch(/\d questions? to answer/)
  })

  it('still names a real can’t on its own card, with the clause crossed on the card it sets up instead', () => {
    const mixed: CantReply = { ...(cant as CantReply), parts: [...(cant as CantReply).parts, NOT_FOLLOWED] }
    const html = draw(mixed)
    expect(text(html)).toContain('I can\'t send email yet Run results show here, in the chat.')
    expect(text(html)).toContain('What I can do instead')
    expect(text(cardOf(html))).toContain('“Colour them by team” I didn’t follow this part.')
    expect(text(cardOf(html))).not.toMatch(/email/i)
  })
})

describe('a can’t answer with nothing it can’t do', () => {
  it('draws no can’t card, since the clauses it didn’t follow are drawn above', () => {
    const notFollowed: PartView = { text: 'only the major releases', mark: 'cant', reason: 'not_followed', note: null, choices: [] }
    const bare: CantReply = { answer: 'cant', cant: [{ kind: 'look_for', text: 'only the major releases', note: 'I didn’t follow this part.', needs: null, system: null, instead: null, unsupported: false }], alternative: null, parts: [notFollowed] }
    expect(draw(bare)).toBe('')
    expect(text(draw(bare, { leftovers: true }))).toBe('Can’t do: “only the major releases” I didn’t follow this part.')
  })
})

describe('a clash inside a watch answer', () => {
  it('is asked on the card inside, and never drawn above it too', () => {
    const clash: PartView = { text: 'Monday and Friday', mark: 'cant', reason: 'one_day', note: null, choices: ['Monday', 'Friday'] }
    const notFollowed: PartView = { text: 'only the major releases', mark: 'cant', reason: 'not_followed', note: null, choices: [] }
    const watch: WatchlistReply = { ...(ownTime as WatchlistReply), also: { ...(setupClash as SetupCardReply), parts: [] }, parts: [clash, notFollowed] }
    const above = text(draw(watch, { leftovers: true }))
    expect(above).toContain('“only the major releases”')
    expect(above).not.toContain('Monday and Friday')
    expect(text(draw(watch)).match(/Monday or Friday\?/g)).toHaveLength(1)
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
    expect(text(cardOf(html))).toContain('Can’t do: Email it to the team. I can\'t send email yet.')
    expect(buttons(html)).toEqual(expect.arrayContaining(['Set up the part I can', 'Ask the team']))
    const rows = text(cardOf(html)).split('Can’t do:')[0]?.split(' Draft ')[1] ?? ''
    expect(rows, 'the ticked rows hold only the part it can do').toContain('Sum them up')
    expect(rows).not.toMatch(/email/i)
  })

  it('keeps a can’t row as a cross even when no part names it, its note standing in for empty text', () => {
    const empty: PartReply = { ...(part as PartReply), parts: [], cant: [{ kind: 'do', text: '', note: 'Email isn’t connected.', needs: 'new_system', system: 'email', instead: null, unsupported: false }] }
    expect(text(draw(empty))).toContain('Can’t do: Email isn’t connected.')
  })

  it('shows the alternative under its own heading, with Ask the team first when there is no alternative', () => {
    const html = draw(cant as CantReply)
    expect(text(html)).toContain('What I can do instead')
    expect(buttons(html)).toContain('Set up')
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

  it('leads a card named for the software it is about, with the sections it looked at as links', () => {
    const html = draw(question as QuestionReply)
    expect(html).toMatch(/<h3 id="[^"]*">LangGraph<\/h3>/)
    expect(text(html)).toBe('LangGraph Looked at Software')
    expect(links(html)).toEqual([['/software', 'Software']])
    expect(buttons(html)).toEqual(['Software'])
  })

  it('links each section to the screen it was read from, Needs you to the Workflows page, where Needs you leads', () => {
    const html = draw({ ...(question as QuestionReply), looked_at: ['watchlist', 'workflows', 'needs_you'] })
    expect(text(html)).toBe('LangGraph Looked at Software Workflows Needs you')
    expect(links(html)).toEqual([
      ['/software', 'Software'],
      ['/workflows', 'Workflows'],
      ['/workflows', 'Needs you'],
    ])
  })

  it('has no Looked at line, and no card, for the fixed fallback, which looked at nothing and names no software', () => {
    expect(draw({ ...(question as QuestionReply), looked_at: [], about_software: [] })).toBe('')
  })

  it('draws plain links, so the keyboard reaches each one, with no tab stop removed and no motion', () => {
    const html = draw({ ...(question as QuestionReply), looked_at: ['watchlist', 'workflows', 'needs_you'] })
    expect(html).not.toContain('tabindex')
    expect(html).not.toContain('aria-hidden')
    expect(html).not.toContain('animation')
  })
})

describe('an Approver’s answers in the chat (spec 5.3)', () => {
  const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
  const HOME = bobHome as HomeOut
  const NOW = new Date('2026-11-13T15:00:00+08:00')
  const OPS = 'Operators set up workflows. Ask Alice, Carol or Dave.'

  function ask(reply: PlannerReply, seed: { home?: HomeOut; decisions?: DecisionsView; useCases?: readonly UseCaseView[]; memory?: CardMemory; approval?: ApprovalView; extra?: readonly ApprovalView[] } = {}): string {
    const session = createDevSession(null)
    const scope = session.cacheScope()
    const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
    client.setQueryData(['me', scope], BOB)
    client.setQueryData(['dev-users'], [BOB])
    client.setQueryData(['home', scope], seed.home ?? HOME)
    for (const request of (seed.home ?? HOME).approvals) {
      client.setQueryData(['approval', scope, request.approval_id], { ...(bobApproval as ApprovalView), approval_id: request.approval_id, run_id: request.run_id })
    }
    for (const approval of [...(seed.approval ? [seed.approval] : []), ...(seed.extra ?? [])]) client.setQueryData(['approval', scope, approval.approval_id], approval)
    client.setQueryData(['people', scope], people.people)
    client.setQueryData(['use-cases', scope], seed.useCases ?? [])
    for (const useCase of seed.useCases ?? []) if (useCase.last_run) client.setQueryData(['troubleshoot', scope, useCase.last_run.run_id, 0], troubleshooting)
    client.setQueryData(['decisions', scope, reply.answer === 'decided' ? reply.only : null], seed.decisions ?? (decisionsOfBob as DecisionsView))
    const thread = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'asked' }), { type: 'answered', reply, typed: 'asked' })
    return renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
          <MemoryRouter>
            <Thread thread={thread} now={NOW} page={PAGE} {...(seed.memory ? { memory: () => seed.memory! } : {})} />
          </MemoryRouter>
        </ApiProvider>
      </QueryClientProvider>,
    )
  }

  const answerOf = (html: string) => text(/<li[^>]*data-answer="true"[^>]*>([\s\S]*)<\/li>/.exec(html)?.[1] ?? '').replace(/^Planner ?:? /, '')

  it('answers a change with who makes changes, naming the Operators, and nothing to press (ROLE-refuse)', () => {
    const html = ask(operatorsReply as PlannerReply)
    expect(answerOf(html)).toBe(OPS)
    expect(buttons(html)).toEqual([])
  })

  it('answers a question asked beside a change as it would alone, and crosses the change with the same words (FOLLOW-bob-mixed)', () => {
    const html = ask(needsMeOperators as PlannerReply)
    expect(answerOf(html)).toContain(`Can’t do: “pause the morning new-ticket check” ${OPS}`)
    expect(answerOf(html)).toContain('3 things need you')
    expect(answerOf(html)).not.toContain('What is waiting for my yes')
  })

  it('lists his own decisions newest first in the sketch’s decisions card: the workflow, the day with the reason or what the yes led to, and the verdict (ROLE-asks)', () => {
    const html = ask(decidedReply as PlannerReply)
    const said = answerOf(html)
    expect(said).toMatch(/^Your recent decisions /)
    expect(said).toContain('Keep our software up to date Today 9:10 · Wrong version Declined')
    expect(said).toContain('Morning new-ticket check Mon 26 Oct · 1 ticket created Approved')
    expect(said).toContain('Weekly closed-ticket summary Fri 16 Oct · Declined by Alice. Nothing was written. Approved')
    expect(said.indexOf('Today 9:10')).toBeLessThan(said.indexOf('Mon 26 Oct'))
    expect(html.match(/data-decision=/g), 'one row each, which opens its run').toHaveLength(3)
  })

  it('says plainly when he has declined nothing, with no rows (FIX-decisions-detail)', () => {
    const html = ask(decidedDeclines as PlannerReply, { decisions: noDecisions })
    expect(answerOf(html)).toBe('You haven’t declined any requests yet.')
    expect(html).not.toContain('aria-label="Your decisions"')
  })

  it('answers what waits for him with the requests themselves, three cards at most, then how many more', () => {
    const [request] = HOME.approvals
    const many = { ...HOME, approvals: Array.from({ length: 10 }, (_, n) => ({ ...request!, approval_id: `apr_${String(n)}`, run_id: `run_${String(n)}` })), approvals_total: 25, confirmations: [] }
    const html = ask({ answer: 'needs_me', parts: [] }, { home: many })
    expect(answerOf(html)).toMatch(/^These need your yes\. Create 1 Jira ticket Needs your yes Upgrade LangGraph from 1\.2\.14 to 1\.2\.16 Review and decide/)
    expect(buttons(html).filter((name) => name === 'Review and decide')).toHaveLength(3)
    expect(html).toMatch(/<a[^>]*href="\/workflows"[^>]*>22 more<\/a>/)
  })

  it('keeps the card on its request after Bob declines, which takes it off Home’s list, and says what happened (Bob declines)', () => {
    const memory = newCardMemory()
    memory.approvals.keep([{ approvalId: 'apr_01JB8', runId: 'run_01JB8' }])
    const declined: ApprovalView = {
      ...(bobApproval as ApprovalView),
      you_can_decide: false,
      why_not: 'not_open',
      steps: [{ index: 0, label: 'Team approver', status: 'declined', decided_by: 'bob', decided_at: '2026-11-13T01:04:00Z', reason: 'Not this week' }],
    }
    const after = { ...HOME, approvals: [], approvals_total: 0, confirmations: [] }
    for (const reply of [{ answer: 'needs_me', parts: [] }, decideReply] as PlannerReply[]) {
      const html = ask(reply, { home: after, memory, approval: declined })
      expect(answerOf(html)).toMatch(/Create 1 Jira ticket Declined Upgrade LangGraph from 1\.2\.14 to 1\.2\.16 Declined\. Nothing was written\. Open$/)
      expect(answerOf(html)).not.toMatch(/Nothing (waits|is waiting) for your yes/)
      expect(buttons(html)).not.toContain('Review and decide')
    }
  })

  it('after Bob approves one request, its card follows the record with Open, and only the requests still waiting ask him to decide', () => {
    const memory = newCardMemory()
    memory.approvals.keep([
      { approvalId: 'apr_done', runId: 'run_done' },
      { approvalId: 'apr_open', runId: 'run_open' },
    ])
    const approved: ApprovalView = {
      ...(bobApproval as ApprovalView),
      approval_id: 'apr_done',
      run_id: 'run_done',
      you_can_decide: false,
      why_not: 'not_open',
      steps: [{ index: 0, label: 'Team approver', status: 'approved', decided_by: 'bob', decided_at: '2026-11-13T01:04:00Z', reason: null }],
    }
    const stillOpen = { ...(bobApproval as ApprovalView), approval_id: 'apr_open', run_id: 'run_open' }
    const home = { ...HOME, approvals: [{ ...HOME.approvals[0]!, approval_id: 'apr_open', run_id: 'run_open' }], approvals_total: 1, confirmations: [] }
    const html = ask({ answer: 'needs_me', parts: [] }, { home, memory, approval: approved, extra: [stillOpen] })
    const cards = [...html.matchAll(/<section[^>]*>([\s\S]*?)<\/section>/g)].map((match) => text(match[1] ?? ''))
    expect(cards).toEqual([
      'Create 1 Jira ticket Approved Upgrade LangGraph from 1.2.14 to 1.2.16 Approved. Open',
      'Create 1 Jira ticket Needs your yes Upgrade LangGraph from 1.2.14 to 1.2.16 Review and decide',
    ])
  })

  it('leads one request with the sketch’s line', () => {
    const one = { ...HOME, confirmations: [] }
    expect(answerOf(ask({ answer: 'needs_me', parts: [] }, { home: one }))).toMatch(/^This needs your yes\. Create 1 Jira ticket Needs your yes/)
  })

  it('sends an approve to the request to decide there, never a decision in the chat', () => {
    const html = ask(decideReply as PlannerReply)
    expect(answerOf(html)).toContain('I can’t approve or decline for you. Open the request to see exactly what it will write, and decide there.')
    expect(buttons(html)).toContain('Review and decide')
    expect(buttons(html).filter((name) => /^(Approve|Decline)$/.test(name))).toEqual([])
  })

  it('keeps a question asked with an approve, to ask on its own', () => {
    expect(answerOf(ask(decideQuestion as PlannerReply))).toContain('Can’t do: “is LangGraph up to date” Ask this on its own, and I’ll answer it.')
  })

  it('says there is nothing to decide when nothing waits for his yes', () => {
    const quiet = { ...HOME, approvals: [], approvals_total: 0 }
    expect(answerOf(ask(decideReply as PlannerReply, { home: quiet }))).toContain('Nothing is waiting for your yes, so there’s nothing to decide.')
  })

  it('answers what he can ask in the sketch’s three lines', () => {
    const html = ask({ answer: 'abilities', parts: [{ text: 'What can you do', mark: 'will_do', reason: null, note: null, choices: [] }] })
    expect(answerOf(html)).toBe('What I can do Show what waits for your yes Show exactly what a change will write Show your past decisions')
    const unknown = ask({ answer: 'abilities', parts: [{ text: 'What’s the weather', mark: 'cant', reason: 'not_followed', note: null, choices: [] }] })
    expect(answerOf(unknown)).toContain('I didn’t follow that I can show what waits for your yes, and your past decisions.')
  })

  it('gives a refusal with no set-up offered, and his request to open where he decides', () => {
    const html = ask(refused as PlannerReply)
    expect(buttons(html)).toEqual(['Say it another way', 'Review and decide'])
    expect(answerOf(html)).toContain('Nobody approves their own work')
    expect(html.match(/class="[^"]*_primary_[^"]*"/g) ?? [], 'one main button, on the request').toHaveLength(1)
  })

  it('answers in one line when the model is slow or missing, with no starting points and no Connect a model', () => {
    for (const [why, said] of [
      ['too_slow', 'The Planner took too long to read your question. Try again in a moment.'],
      ['no_model', 'I can’t answer questions until an AI model is connected. An Operator can connect one in Settings.'],
    ] as const) {
      const html = ask({ ...(offline as OfflineReply), why })
      expect(answerOf(html)).toBe(said)
      expect(buttons(html)).toEqual([])
    }
  })

  it('offers the newest three requests to open, and says how many more, never the whole of Needs you (fix 7)', () => {
    const [request] = HOME.approvals
    const many = { ...HOME, approvals: Array.from({ length: 10 }, (_, n) => ({ ...request!, approval_id: `apr_${String(n)}`, run_id: `run_${String(n)}` })), approvals_total: 12 }
    const html = ask(decideReply as PlannerReply, { home: many })
    expect(buttons(html).filter((name) => name === 'Review and decide')).toHaveLength(3)
    expect(html).toMatch(/<a[^>]*href="\/workflows"[^>]*>9 more<\/a>/)
    expect(html).not.toMatch(/<h2[^>]*>\s*Needs you/)
  })

  it('speaks of the team’s workflows, and of why one stopped with who can retry, from his Workflows page’s rows', () => {
    const stopped = stoppedUseCase as UseCaseView
    expect(answerOf(ask({ answer: 'check_workflows', use_case_id: null, parts: [] }, { useCases: [stopped] }))).toMatch(/^The team has 1 workflow\. 1 stopped\./)
  })
})

describe('the run card: the AI troubleshooter’s answer that moves with the run', () => {
  const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator'] }
  const BOB_: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
  const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob' }
  const nameOf = (id: string) => NAMES[id] ?? id
  const replay = (raw: readonly { run_id: string; seq: number }[], upTo = Infinity): RunModel => {
    const kept = raw.filter((item) => item.seq <= upTo)
    return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
  }
  const useCase = runUseCase as UseCaseView
  const retriedBy = (model: RunModel, by: string): RunModel =>
    foldWire(model, [{ run_id: 'run_01JB9', seq: model.seq + 1, ts: '2026-11-04T02:20:00Z', actor: { kind: 'user', id: by, display: by }, summary: '', kind: 'run_retried', data: { leg: 'work', attempt: 2 } }], 'run_01JB9')

  function card(model: RunModel, { me = ALICE, beside = false, shownInPanel = false }: { me?: Me; beside?: boolean; shownInPanel?: boolean } = {}): string {
    const story = storyOf({
      run: { run_id: 'run_01JB9', started_at: '2026-11-04T02:14:00Z' },
      live: { shown: model, head: model, loadedUpTo: model.seq },
      me,
      nameOf,
      useCase,
      approval: undefined,
      advice: troubleshooting as TroubleshootingOut,
      adviceLoading: false,
      modelOff: false,
      now: new Date((model.chat.at(-1)?.at ?? 0) + 3_600_000),
    })
    const opener = { shown: shownInPanel ? { kind: 'run' as const, id: 'run_01JB9' } : null, open: () => undefined, show: () => undefined }
    return renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
          <MemoryRouter>
            <OpensInPanel.Provider value={opener}>
              <RunCardView runId="run_01JB9" name="LangGraph release check" story={story} beside={beside} />
            </OpensInPanel.Provider>
          </MemoryRouter>
        </ApiProvider>
      </QueryClientProvider>,
    )
  }
  const pill = (html: string) => /<span class="[^"]*pill[^"]*"[^>]*>([^<]*)<\/span>/.exec(html)?.[1]
  const labels = (html: string) => [...html.matchAll(/<dt>([^<]*)<\/dt>/g)].map((match) => match[1])

  it('stopped: the head and its pill, the line, the three answers, and Open and Retry', () => {
    const html = card(replay(runFailure))
    expect(text(html)).toContain('LangGraph release check Stopped')
    expect(html).toContain('aria-label="Steps of this run"')
    expect(labels(html)).toEqual(['What happened', 'Affected', 'Safe to retry'])
    expect(buttons(html)).toEqual(['Open', 'Retry'])
    expect(whoOf({ answer: 'why_stopped', use_case_id: null, parts: [] })).toBe('troubleshooter')
  })

  it('stopped, asked by an Approver: the same answers, and who can retry in place of a button', () => {
    const html = card(replay(runFailure), { me: BOB_ })
    expect(labels(html)).toEqual(['What happened', 'Affected', 'Safe to retry'])
    expect(buttons(html)).toEqual(['Open'])
    expect(text(html)).toContain('An Operator can retry the run.')
  })

  it('retrying: the same card says Now, with no stop’s answers and no second Retry', () => {
    const html = card(retriedBy(replay(runFailure), 'alice'))
    expect(pill(html)).toBe('Running')
    expect(labels(html)).toEqual(['Now'])
    expect(text(html)).toContain('Retrying after a short wait…')
    expect(buttons(html)).toEqual(['Open'])
  })

  it('waiting: what it found and that it waits for a yes, and nothing written yet', () => {
    const html = card(replay(runSuccess, 15))
    expect(pill(html)).toBe('Waiting for a yes')
    expect(labels(html)).toEqual(['Found', 'Now'])
    expect(text(html)).toContain('Waiting for a yes.')
    expect(html).not.toMatch(/MOCK-142/)
  })

  it('done: folds to the head and one settled line, the ticket said once', () => {
    const html = card(replay(runSuccess))
    expect(pill(html)).toBe('Done')
    expect(text(html)).toContain('Done at 10:20 · MOCK-142 created after Bob’s yes')
    expect(labels(html)).toEqual([])
    expect(html).not.toContain('aria-label="Steps of this run"')
    expect(text(html).match(/MOCK-142/g)).toHaveLength(1)
  })

  it('declined: one line that says nothing was written, and never a ticket', () => {
    const html = card(replay(runRejected))
    expect(pill(html)).toBe('Declined')
    expect(text(html)).toContain('Ended at 10:18 · Bob declined: wrong version. Nothing was written.')
    expect(html).not.toMatch(/created|MOCK-/)
    expect(labels(html)).toEqual([])
  })

  it('beside the chat: drops its line, its Open and its Retry, which the panel has, and keeps its answers (a flow shows once)', () => {
    const html = card(replay(runFailure), { beside: true, shownInPanel: true })
    expect(html).not.toContain('aria-label="Steps of this run"')
    expect(buttons(html)).toEqual([])
    expect(labels(html)).toHaveLength(3)
  })

  it('beside the chat when finished: drops its settled line too, which the panel keeps under its own line', () => {
    const html = card(replay(runSuccess), { beside: true, shownInPanel: true })
    expect(pill(html)).toBe('Done')
    expect(text(html)).not.toContain('Done at')
  })

  it('a stop that can’t be retried offers Report to support once: on the card, or in the panel while the panel shows the run', () => {
    const unretryable = replay(runFailure.map((item) => (item.kind === 'run_failed' ? { ...item, data: { ...item.data, retryable: false } } : item)))
    expect(buttons(card(unretryable))).toEqual(['Open', 'Report to support'])
    expect(buttons(card(unretryable, { beside: true, shownInPanel: true }))).toEqual([])
  })

  it('keeps following its run when the chat draws it again, after a retry took the run off the stopped list', () => {
    const why: PlannerReply = { answer: 'why_stopped', use_case_id: null, parts: [] }
    const thread = threadReducer(threadReducer(EMPTY, { type: 'sent', text: 'Why did it stop?' }), { type: 'answered', reply: why, typed: 'Why did it stop?' })
    const drawn = (memory: (id: number) => CardMemory = () => newCardMemory()): string => {
      const session = createDevSession(null)
      const scope = session.cacheScope()
      const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
      client.setQueryData(['me', scope], ALICE)
      client.setQueryData(['dev-users'], [ALICE])
      client.setQueryData(['home', scope], { ...(bobHome as HomeOut), stopped: [] })
      client.setQueryData(['people', scope], people.people)
      client.setQueryData(['use-cases', scope], [])
      return text(
        renderToStaticMarkup(
          <QueryClientProvider client={client}>
            <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
              <MemoryRouter>
                <Thread thread={thread} now={new Date('2026-11-04T12:00:00+08:00')} page={PAGE} memory={memory} />
              </MemoryRouter>
            </ApiProvider>
          </QueryClientProvider>,
        ),
      )
    }
    expect(drawn(), 'a card that kept no run finds nothing stopped').toContain('Nothing has stopped right now.')
    const kept = newCardMemory()
    kept.run.keep('run_01JB9')
    const again = drawn(() => kept)
    expect(again, 'the card kept its run with the message').not.toContain('Nothing has stopped right now.')
    expect(again).toContain('Reading the run')
  })

  /** One stream for one card: the stop, Alice's retry, then the run waits for a yes, writes and is done. */
  const STREAM = [
    ...runFailure,
    { run_id: 'run_01JB9', seq: 15, ts: '2026-11-04T02:20:00Z', actor: { kind: 'user', id: 'alice', display: 'Alice' }, summary: '', kind: 'run_retried', data: { leg: 'work', attempt: 2 } },
    ...runSuccess.filter((item) => item.seq > 1).map((item) => ({ ...item, run_id: 'run_01JB9', seq: item.seq + 14, ts: item.ts.replace('2026-11-03T02:', '2026-11-04T03:') })),
  ]

  it('moves in place from the run’s stream: the one card goes stopped, retrying, waiting, writing, then done', () => {
    const frames: string[] = []
    STREAM.reduce((model, item) => {
      const next = foldWire(model, [item], 'run_01JB9')
      if (next.seq >= 14) frames.push(card(next))
      return next
    }, emptyModel)
    const stageOfFrame = (html: string): string => {
      const said = text(html)
      if (pill(html) === 'Stopped') return 'stopped'
      if (said.includes('Now Retrying after a short wait…')) return 'retrying'
      if (pill(html) === 'Waiting for a yes' && said.includes('Now Waiting for a yes.')) return 'waiting'
      if (said.includes('Now Bob said yes. Creating the ticket…')) return 'writing'
      if (pill(html) === 'Done' && said.includes('MOCK-142 created after Bob’s yes')) return 'done'
      return `unexpected: ${said}`
    }
    const stages = frames.map(stageOfFrame).filter((stage, index, all) => stage !== all[index - 1])
    expect(stages).toEqual(['stopped', 'retrying', 'waiting', 'writing', 'done'])
    const heads = new Set(frames.map((html) => /^<section[^>]*><div[^>]*><h3[^>]*>([^<]*)<\/h3>/.exec(html)?.[1]))
    expect(heads, 'every frame is the same card, headed by the run’s workflow').toEqual(new Set(['LangGraph release check']))
  })
})
