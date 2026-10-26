import { describe, expect, it } from 'vitest'
import { QUESTS, type Quest } from './quests'
import { TOUR_STOPS } from './stops'
import { FRESH, alreadyMet, parseTour, pathMatches, placeOf, shownStep, tourStep, type TourAction, type TourState } from './tourState'

const TWO: readonly Quest[] = [
  {
    id: 'one',
    title: 'One',
    steps: [
      { id: 'a', label: 'A', say: 'Do A.', done: { kind: 'read' } },
      { id: 'b', label: 'B', say: 'Do B.', done: { kind: 'press', stop: 'theme' } },
    ],
  },
  { id: 'two', title: 'Two', steps: [{ id: 'c', label: 'C', say: 'Do C.', done: { kind: 'page', at: '/jira' } }] },
]

function play(...actions: TourAction[]): TourState {
  return actions.reduce((state, action) => tourStep(state, action, TWO), tourStep(FRESH, { type: 'open' }, TWO))
}

describe('moving through the tour', () => {
  it('ticks a step only when the step on show is the one done', () => {
    const state = play({ type: 'done', id: 'b' })
    expect(state).toMatchObject({ quest: 0, step: 0, ticked: [] })
    expect(play({ type: 'done', id: 'a' })).toMatchObject({ quest: 0, step: 1, ticked: ['a'] })
  })

  it('moves past a skipped step without ticking it', () => {
    expect(play({ type: 'skip' })).toMatchObject({ step: 1, ticked: [] })
  })

  it('pauses at the end of a quest until the person starts the next one', () => {
    const state = play({ type: 'done', id: 'a' }, { type: 'done', id: 'b' })
    expect(placeOf(state, TWO)).toMatchObject({ is: 'quest_done', quest: { id: 'one' } })
    expect(placeOf(tourStep(state, { type: 'next_quest' }, TWO), TWO)).toMatchObject({ is: 'step', step: { id: 'c' } })
  })

  it('goes back across a quest, and from the end of the tour', () => {
    const atC = play({ type: 'skip' }, { type: 'skip' }, { type: 'next_quest' })
    expect(tourStep(atC, { type: 'back' }, TWO)).toMatchObject({ quest: 0, step: 1 })
    const finished = tourStep(atC, { type: 'done', id: 'c' }, TWO)
    const ended = tourStep(finished, { type: 'next_quest' }, TWO)
    expect(placeOf(ended, TWO).is).toBe('tour_done')
    expect(tourStep(ended, { type: 'back' }, TWO)).toMatchObject({ quest: 1, step: 0 })
    expect(tourStep(play(), { type: 'back' }, TWO)).toMatchObject({ quest: 0, step: 0 })
  })

  it('starts again when opened after the end, and keeps its place when opened mid way', () => {
    const ended = play({ type: 'skip' }, { type: 'skip' }, { type: 'next_quest' }, { type: 'skip' }, { type: 'next_quest' })
    const closed = tourStep(ended, { type: 'close' }, TWO)
    expect(tourStep(closed, { type: 'open' }, TWO)).toEqual({ ...FRESH, open: true })
    const midway = tourStep(play({ type: 'done', id: 'a' }, { type: 'fold', folded: true }), { type: 'close' }, TWO)
    expect(tourStep(midway, { type: 'open' }, TWO)).toMatchObject({ open: true, folded: false, step: 1, ticked: ['a'] })
  })
})

describe('what the browser kept', () => {
  it('reads back what it wrote', () => {
    const state = play({ type: 'done', id: 'a' })
    expect(parseTour(JSON.stringify(state), TWO)).toEqual(state)
  })

  it('starts fresh from junk, or from a place that no longer exists', () => {
    for (const junk of [null, '', 'not json', '42', '[]', '{"quest":"1","step":0}', '{"quest":0,"step":3}', '{"quest":5,"step":0}', '{"quest":2,"step":1}', '{"quest":-1,"step":0}']) {
      expect(parseTour(junk, TWO)).toEqual(FRESH)
    }
    expect(parseTour('{"quest":2,"step":0,"ticked":["a",7]}', TWO)).toMatchObject({ quest: 2, ticked: ['a'] })
  })
})

describe('when a step is met', () => {
  it('matches one page, or any one run', () => {
    expect(pathMatches('/runs/*', '/runs/run_1')).toBe(true)
    expect(pathMatches('/runs/*', '/runs')).toBe(false)
    expect(pathMatches('/runs/*', '/runs/')).toBe(false)
    expect(pathMatches('/approvals', '/approvals/')).toBe(true)
    expect(pathMatches('/approvals', '/approvals/apr_1')).toBe(false)
    expect(pathMatches('/', '/')).toBe(true)
    expect(pathMatches('/', '/builder')).toBe(false)
  })

  it('knows who the person is acting as', () => {
    const bob = { id: 'bob', roles: ['approver'] }
    expect(alreadyMet({ kind: 'user', id: 'bob' }, '/', bob)).toBe(true)
    expect(alreadyMet({ kind: 'role', role: 'operator' }, '/', bob)).toBe(false)
    expect(alreadyMet({ kind: 'role', role: 'operator' }, '/', null)).toBe(false)
    expect(alreadyMet({ kind: 'press', stop: 'theme' }, '/', bob)).toBe(false)
  })

  it('turns a user switch into words to read when there is no user menu', () => {
    const switchToBob = QUESTS.flatMap((quest) => quest.steps).find((step) => step.id === 'be-bob')
    if (!switchToBob) throw new Error('be-bob is gone')
    expect(shownStep(switchToBob, true)).toBe(switchToBob)
    expect(shownStep(switchToBob, false)).toMatchObject({ done: { kind: 'read' }, say: switchToBob.signedIn })
    expect(shownStep(switchToBob, false).glow).toBeUndefined()
  })
})

describe('the quests', () => {
  const steps = QUESTS.flatMap((quest) => quest.steps)

  it('give every step its own id', () => {
    expect(new Set(steps.map((step) => step.id)).size).toBe(steps.length)
  })

  it('point only at stops the screens can mark', () => {
    const stops = new Set<string>(TOUR_STOPS)
    for (const step of steps) {
      if (step.glow) expect(stops.has(step.glow)).toBe(true)
      if (step.done.kind === 'press' || step.done.kind === 'see') expect(stops.has(step.done.stop)).toBe(true)
    }
  })

  it('send the person back only to pages a link can reach', () => {
    for (const step of steps) {
      if (step.where) expect(step.where.to ?? step.where.at).not.toContain('*')
    }
  })

  it('use plain punctuation, with no dashes the sponsor would trip on', () => {
    for (const step of steps) {
      for (const words of [step.say, step.why ?? '', step.signedIn ?? '']) expect(words).not.toMatch(/[—–’]/)
    }
  })
})
