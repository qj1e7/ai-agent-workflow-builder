import { describe, expect, it } from 'vitest'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import capabilitiesTrouble from '../../../../contracts/fixtures/planner/capabilities.trouble.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import watchlist from '../../../../contracts/fixtures/planner/answer.watchlist.json'
import type { CantReply, CapabilitiesView, PartReply, PlannerReply, SetupCardReply, WatchlistReply } from '../../api/types'
import {
  capabilityGroups,
  cantLine,
  cardLines,
  lineText,
  needsSay,
  refusalNext,
  sayOf,
  setupTask,
  startingPoints,
  stateWords,
  TAG_CANT,
  TAG_CHOICE,
  TAG_FILLED,
  watchlistSay,
  whyNot,
} from './answers'

const CARD = setupCard as SetupCardReply
const PART = part as PartReply
const CANT = cant as CantReply
const CAPS = capabilities as CapabilitiesView

describe('a part of the request on the card', () => {
  it('says “Filled in by me” only for what the Planner read into the words, and shows what the person said', () => {
    const lines = cardLines(CARD.rows)
    expect(lines.map((line) => [line.label, line.tag])).toEqual([
      ['When', null],
      ['Looks for', TAG_FILLED],
      ['Does', null],
      ['Where it goes', null],
    ])
    expect(lines[1]?.note).toContain('You said')
  })

  it('names a missing part and never guesses a time', () => {
    const [line] = cardLines([{ kind: 'schedule', text: '', state: 'missing', note: null }])
    expect(line).toMatchObject({ text: 'No time chosen yet', tag: TAG_CHOICE })
  })

  it('shows a can’t-do part’s note when its text is empty, so a line is never blank', () => {
    const [line] = cardLines([{ kind: 'do', text: '', state: 'cant_do', note: 'Email isn’t connected.' }])
    expect(line).toMatchObject({ text: 'Email isn’t connected.', tag: TAG_CANT, note: null })
    expect(lineText({ kind: 'where', text: ' ', note: null })).toBe('Not said yet')
  })
})

describe('a can’t row', () => {
  it('keeps its text and its note apart', () => {
    const line = cantLine(CANT.cant[0]!)
    expect(line.text).toBe('email it to the team')
    expect(line.note).toContain('I can\'t email it to the team.')
  })

  it('shows the note in place of empty text, and a plain line when it has neither', () => {
    expect(cantLine({ text: '', note: 'No email yet.' })).toEqual({ text: 'No email yet.', note: '' })
    expect(cantLine({ text: '', note: '  ' }).text).toBe('The platform can’t do this yet.')
  })

  it('does not say the same words twice', () => {
    expect(cantLine({ text: 'send email', note: 'send email' })).toEqual({ text: 'send email', note: '' })
  })
})

describe('the sentence for each answer', () => {
  const answers: Record<string, PlannerReply> = { card: CARD, part: PART, cant: CANT, refused: refused as PlannerReply }

  it('never promises more than the answer’s own kind', () => {
    expect(sayOf(answers['card']!)).toBe('Here’s what I understood. I filled in what I could.')
    expect(sayOf(answers['part']!)).toContain('I can do part of that.')
    expect(sayOf(answers['cant']!)).toBe('I can’t do all of that, but I can set up something close.')
    expect(sayOf({ ...CANT, alternative: null })).toBe('I can’t do that yet.')
    expect(sayOf(answers['refused']!)).toBe('I can’t set that up. Anything that changes data waits for a yes, every time.')
  })

  it('leaves the three state answers to the pages’ own functions', () => {
    for (const answer of ['check_workflows', 'why_stopped', 'needs_me'] as const) {
      expect(sayOf({ answer, use_case_id: null })).toBeNull()
    }
  })

  it('says a watched piece of software is on the list, or why it belongs there, without a schedule it can’t promise', () => {
    const reply = watchlist as WatchlistReply
    expect(sayOf(reply)).toBe('LangGraph is already on the Software watchlist.')
    expect(watchlistSay('Kubernetes', false)).toContain('Kubernetes is software, so it belongs on the Software watchlist')
    expect(watchlistSay('Kubernetes', false)).not.toMatch(/Monday|every/i)
    expect(watchlistSay(null, false)).toContain('belongs on the Software watchlist')
  })

  it('counts what needs her in one sentence', () => {
    expect(needsSay(0)).toBe('Nothing needs you right now.')
    expect(needsSay(1)).toBe('1 thing needs you.')
    expect(needsSay(2)).toBe('2 things need you.')
  })
})

describe('what a refusal hands back', () => {
  it('returns the rest of the request to the Planner’s answer, never to a set-up, because it can ask for more', () => {
    expect(refusalNext(refused)).toEqual({ rest: 'Create the ticket' })
    expect(refusalNext({ rest: '  ' })).toEqual({ rest: null })
  })
})

describe('what the old New workflow is handed', () => {
  it('is the typed words for a card or a part', () => {
    expect(setupTask(CARD, 'Every Friday, sum up the closed tickets')).toBe('Every Friday, sum up the closed tickets')
    expect(setupTask(PART, 'sum up and email')).toBe('sum up and email')
  })

  it('is the alternative’s own words for a can’t, so it never reads the part it can’t do again', () => {
    expect(setupTask(CANT, 'email me the weekly list')).toBe('Every Friday. Tickets closed this week in MOCK. Sum them up in one new ticket. In the MOCK project')
    expect(setupTask({ ...CANT, alternative: null }, 'email me the list')).toBe('email me the list')
  })
})

describe('the I can and Not yet lists', () => {
  it('split by the state the platform gave each entry', () => {
    const groups = capabilityGroups(CAPS)
    expect(groups.can.every((entry) => entry.state === 'ready')).toBe(true)
    expect(groups.notYet.map((entry) => entry.id)).toContain('jira.find_older')
    expect(groups.can.length + groups.setup.length + groups.notYet.length).toBe(CAPS.capabilities.length)
  })

  it('puts an entry with a connection that needs setup or is down in its own group, with the platform’s fix', () => {
    const trouble = capabilitiesTrouble as CapabilitiesView
    const groups = capabilityGroups(trouble)
    expect(groups.setup.length).toBeGreaterThan(0)
    for (const entry of groups.setup) expect(stateWords(entry)).toMatch(/Needs setup|Not answering right now/)
    expect(whyNot(groups.setup[0]!)).not.toBe('')
  })

  it('offers only examples that set something up, which the platform vouches for', () => {
    expect(startingPoints(CAPS)).toEqual(['Every Friday, sum up the tickets we closed this week', 'Keep track of the React version'])
  })
})
