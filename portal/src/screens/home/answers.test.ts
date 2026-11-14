import { describe, expect, it } from 'vitest'
import cant from '../../../../contracts/fixtures/planner/answer.cant.json'
import capabilities from '../../../../contracts/fixtures/planner/capabilities.json'
import capabilitiesTrouble from '../../../../contracts/fixtures/planner/capabilities.trouble.json'
import part from '../../../../contracts/fixtures/planner/answer.part.json'
import question from '../../../../contracts/fixtures/planner/answer.question.json'
import refused from '../../../../contracts/fixtures/planner/answer.refused.json'
import setupCard from '../../../../contracts/fixtures/planner/answer.setup_card.json'
import watchlist from '../../../../contracts/fixtures/planner/answer.watchlist.json'
import type { Row } from '../workflows/workflow'
import type { CantReply, CapabilitiesView, PartReply, PlannerReply, SetupCardReply, WatchlistReply } from '../../api/types'
import {
  capabilityGroups,
  workflowsSay,
  cantLine,
  cardLines,
  ideasSay,
  lineText,
  needsSay,
  refusalNext,
  sayOf,
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
    expect(line.note).toBe('I can\'t send email yet.')
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
    expect(sayOf({ ...(answers['card'] as SetupCardReply), similar: null })).toBe('Here’s what I understood.')
    expect(sayOf(answers['card']!), 'a workflow of the same name leads with the one she has').toBe('You already have this one.')
    expect(sayOf(answers['part']!), 'the sketch leads every set-up card the same way, a cross or not').toBe('Here’s what I understood.')
    expect(sayOf(answers['cant']!)).toBe('I can’t do all of that, but I can set up something close.')
    expect(sayOf({ ...CANT, alternative: null }), 'its one-line card says it').toBeNull()
    const own = { ...CANT, alternative: null, cant: CANT.cant.map((row) => ({ ...row, instead: null })) }
    expect(sayOf(own)).toBe('I can’t do that yet.')
    expect(sayOf(answers['refused']!)).toBe('I can’t set that up. Anything that changes data waits for a yes, every time.')
  })

  it('says a question answer in the Planner’s own words, not in fixed text', () => {
    expect(sayOf(question as PlannerReply)).toBe('LangGraph is behind. You run 1.2.14 and the newest is 1.2.16.')
  })

  it('leaves the three state answers to the pages’ own functions', () => {
    for (const answer of ['check_workflows', 'why_stopped', 'needs_me'] as const) {
      expect(sayOf({ answer, use_case_id: null, parts: [] })).toBeNull()
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

describe('the chat sentence for a set-up card (inconsistency I8)', () => {
  it('carries no count, because the card’s footer, from setupLeft, is the only count', () => {
    for (const reply of [CARD, PART] as PlannerReply[]) expect(sayOf(reply)).not.toMatch(/\d|choice|left/i)
  })
})

describe('the lists Home shows without being asked', () => {
  it('split by the state the platform gave each entry', () => {
    const groups = capabilityGroups(CAPS)
    expect(groups.can.every((entry) => entry.state === 'ready')).toBe(true)
    expect(groups).not.toHaveProperty('notYet')
  })

  it('hold only what software versioning uses, and every one of those', () => {
    const groups = capabilityGroups(CAPS)
    const focus = CAPS.capabilities.filter((entry) => entry.focus)
    expect(focus.map((entry) => entry.id).sort()).toEqual(['github.releases', 'jira.create', 'teams.ask'])
    expect(groups.can.map((entry) => entry.id).sort()).toEqual(focus.map((entry) => entry.id).sort())
  })

  it('leave out every other capability, in the lists and in the trouble view', () => {
    for (const view of [CAPS, capabilitiesTrouble as CapabilitiesView]) {
      const groups = capabilityGroups(view)
      const shown = [...groups.can, ...groups.setup].map((entry) => entry.id)
      expect(shown.length).toBeGreaterThan(0)
      for (const entry of view.capabilities.filter((item) => !item.focus)) expect(shown).not.toContain(entry.id)
    }
  })

  it('puts an entry with a connection that needs setup or is down in its own group, with the platform’s fix', () => {
    const trouble = capabilitiesTrouble as CapabilitiesView
    const groups = capabilityGroups(trouble)
    expect(groups.setup.length).toBeGreaterThan(0)
    for (const entry of groups.setup) expect(stateWords(entry)).toMatch(/Needs setup|Not answering right now/)
    expect(whyNot(groups.setup[0]!)).not.toBe('')
  })

  it('offers only examples that set something up, which the platform vouches for', () => {
    expect(startingPoints(CAPS)).toEqual(['Keep track of the LangGraph version'])
  })
})

describe('Check my workflows counts what its rows show', () => {
  const caseOf = (id: string, state: 'on' | 'paused', last: string | null) =>
    ({ use_case_id: id, state, last_run: last === null ? null : { state: last } }) as unknown as Row['useCase']
  const row = (id: string, last: string | null, state: 'on' | 'paused' = 'on'): Row => ({ useCase: caseOf(id, state, last), action: null })

  it('says running only for a run in progress, never for a workflow that is simply idle', () => {
    const rows = [row('a', 'failed'), row('b', 'awaiting_approval'), row('c', null), row('d', 'succeeded'), row('e', 'working')]
    expect(workflowsSay(rows)).toBe('You have 5 workflows. 1 stopped, 1 is waiting for a yes, 1 is running.')
    expect(workflowsSay([row('c', null), row('d', 'succeeded')])).toBe('You have 2 workflows. None needs you.')
  })
})

describe('Set up another workflow counts its places to start (FIX-starts-count)', () => {
  const CAPS = capabilities as CapabilitiesView

  it('says as many places as the chips under it show', () => {
    const places = startingPoints(CAPS).length
    expect(places).toBeGreaterThan(0)
    expect(ideasSay(places)).toBe(places === 1 ? 'Here is a place to start. Pick it, or tell me something else.' : `Here are ${String(places)} places to start. Pick one, or tell me something else.`)
  })

  it('reads right for one place, two places and none', () => {
    expect(ideasSay(1)).toBe('Here is a place to start. Pick it, or tell me something else.')
    expect(ideasSay(2)).toBe('Here are 2 places to start. Pick one, or tell me something else.')
    expect(ideasSay(0)).toContain('no places to start')
  })

  it('is said by the list under it, so the reply itself carries no fixed count', () => {
    expect(sayOf({ answer: 'ideas', parts: [] })).toBeNull()
  })
})
