import { describe, expect, it } from 'vitest'
import openapi from '../../../../contracts/openapi.json'
import confirmationsAlice from '../../../../contracts/fixtures/people/confirmations.alice.json'
import confirmationsBob from '../../../../contracts/fixtures/people/confirmations.bob.json'
import decideRefusal from '../../../../contracts/fixtures/people/decide-refusal.you_asked.json'
import list from '../../../../contracts/fixtures/people/list.json'
import personApprover from '../../../../contracts/fixtures/people/person.approver.json'
import ownOperatorRole from '../../../../contracts/fixtures/people/refusal.own_operator_role.json'
import twoApprovers from '../../../../contracts/fixtures/people/refusal.two_approvers.json'
import history from '../../../../contracts/fixtures/settings/history.json'
import modelActive from '../../../../contracts/fixtures/settings/model.active.json'
import modelEmpty from '../../../../contracts/fixtures/settings/model.empty.json'
import pendingAlice from '../../../../contracts/fixtures/settings/model.pending.alice.json'
import pendingBob from '../../../../contracts/fixtures/settings/model.pending.bob.json'
import { ApiError } from '../../api/client'
import type { ConfirmationOut, DecideRefusal, Me, ModelOut, ModelSettingsView, PeopleRefusal, PersonOut, SettingsChangeOut } from '../../api/types'
import {
  approverConfirmationsByPerson,
  canChangeSettings,
  CHECK_WHAT_YOU_TYPED_WORDS,
  decidedApproverWords,
  decideRefusalWords,
  fieldOfProblem,
  historyOf,
  keyEndingWords,
  leftTheListWords,
  modelNeedsYou,
  needsYou,
  NOT_ACCEPTED_WORDS,
  NOT_SIGNED_IN_WORDS,
  peopleRefusalWords,
  pendingApproverFor,
  personStatusWords,
  saidAfterListChange,
  savedKeyFits,
  SETTINGS_OFF_WORDS,
  settingsErrorWords,
  startingProvider,
  tabFrom,
  type NotFound,
  type PeopleSaid,
} from './settings'

const schemas = (openapi as unknown as { components: { schemas: Record<string, { enum?: string[] }> } }).components.schemas
const PEOPLE_REFUSALS = schemas['PeopleRefusal']?.enum as PeopleRefusal[]
const DECIDE_REFUSALS = schemas['DecideRefusal']?.enum as DecideRefusal[]

const PEOPLE = list.people as PersonOut[]
const DAVE = PEOPLE.find((person) => person.display === 'Dave') as PersonOut
const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'], on_list: true }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'], on_list: true }
const CAROL: Me = { id: 'carol', display: 'Carol', roles: ['operator'], on_list: true }
const FOR_ALICE = confirmationsAlice.confirmations as ConfirmationOut[]
const FOR_BOB = confirmationsBob.confirmations as ConfirmationOut[]
const ACTIVE = modelActive.active as ModelOut

const LOOKS_LIKE_A_CODE = /\b\d{3}\b|[a-z]+_[a-z_]+|[A-Z]{2,}_[A-Z_]+/

describe('the refusal words', () => {
  it('cover every PeopleRefusal value in the contract, in plain words', () => {
    expect(PEOPLE_REFUSALS.length).toBeGreaterThan(0)
    expect(Object.keys(peopleRefusalWords).sort()).toEqual([...PEOPLE_REFUSALS].sort())
    for (const refusal of PEOPLE_REFUSALS) {
      const words = settingsErrorWords(new ApiError(409, { refusal, message: 'from the platform' }), 'dev')
      expect(words, refusal).toBe(peopleRefusalWords[refusal])
      expect(words, refusal).not.toMatch(LOOKS_LIKE_A_CODE)
    }
  })

  it('cover every DecideRefusal value in the contract, whether the platform answers 403 or 409', () => {
    expect(DECIDE_REFUSALS.length).toBeGreaterThan(0)
    expect(Object.keys(decideRefusalWords).sort()).toEqual([...DECIDE_REFUSALS].sort())
    for (const refusal of DECIDE_REFUSALS) {
      for (const status of [403, 409]) {
        const words = settingsErrorWords(new ApiError(status, { refusal, message: 'from the platform' }), 'dev', 'confirmation')
        expect(words, `${refusal} ${status}`).toBe(decideRefusalWords[refusal])
        expect(words, refusal).not.toMatch(LOOKS_LIKE_A_CODE)
      }
    }
  })

  it('explain the two floors the way the fixtures refuse them', () => {
    expect(settingsErrorWords(new ApiError(409, twoApprovers), 'dev')).toBe('At least 2 people must be Approvers, so nobody has to approve their own work.')
    expect(settingsErrorWords(new ApiError(409, { refusal: 'last_operator', message: '' }), 'dev')).toBe(
      'At least 1 person must stay an Operator, so someone can still change settings.',
    )
    expect(settingsErrorWords(new ApiError(409, ownOperatorRole), 'dev')).toBe('You can’t take away your own Operator role. Ask another Operator.')
    expect(settingsErrorWords(new ApiError(403, decideRefusal), 'dev', 'confirmation')).toBe(decideRefusalWords.you_asked)
  })

  it('never show a code for any other answer', () => {
    const cases: [ApiError | Error, NotFound, string][] = [
      [new ApiError(422, { detail: [{ loc: ['body', 'email'], msg: 'too short', type: 'string_too_short' }] }), 'person', CHECK_WHAT_YOU_TYPED_WORDS],
      [new ApiError(404, { detail: 'No such person on the list' }), 'person', 'That person is no longer on the list. The list now shows who is on it.'],
      [new ApiError(404, { detail: 'No such confirmation' }), 'confirmation', 'This request is no longer waiting. The page now shows where it stands.'],
      [new ApiError(503, { detail: 'Settings are off until SETTINGS_ENCRYPTION_KEY is set for platform-api.' }), 'address', SETTINGS_OFF_WORDS],
      [new ApiError(418, null), 'person', NOT_ACCEPTED_WORDS],
      [new ApiError(500, null), 'person', 'The platform had a problem. Try again in a moment.'],
      [new TypeError('Failed to fetch'), 'person', 'The platform could not be reached. Check the connection and try again.'],
    ]
    for (const [error, missing, words] of cases) {
      const said = settingsErrorWords(error, 'dev', missing)
      expect(said).toBe(words)
      expect(said).not.toMatch(LOOKS_LIKE_A_CODE)
    }
  })

  it('name the person a change was about when the platform no longer has them', () => {
    const gone = new ApiError(404, { detail: 'No such person on the list' })
    expect(settingsErrorWords(gone, 'dev', 'person', 'Gina')).toBe('Gina is no longer on the list. The list now shows who is on it.')
    expect(settingsErrorWords(gone, 'dev', 'confirmation', 'Gina')).toBe('This request is no longer waiting. The page now shows where it stands.')
  })

  it('pass on the platform’s own plain words for an address it refused', () => {
    const own = new ApiError(403, { detail: 'You entered this address, so another Approver must confirm it.' })
    expect(settingsErrorWords(own, 'dev', 'address')).toBe('You entered this address, so another Approver must confirm it.')
  })
})

describe('a waiting Approver request', () => {
  const forAlice = approverConfirmationsByPerson(FOR_ALICE).get(DAVE.id)
  const forBob = approverConfirmationsByPerson(FOR_BOB).get(DAVE.id)

  it('lets an Approver who did not ask confirm it or say not now', () => {
    expect(pendingApproverFor(forBob, DAVE, BOB, 'Alice')).toEqual({ can: 'decide' })
  })

  it('tells the Operator who asked that someone else must confirm it', () => {
    expect(pendingApproverFor(forAlice, DAVE, ALICE, 'Alice')).toEqual({ can: 'nothing', words: 'Asked by you, so another Approver must confirm it.' })
  })

  it('tells an Operator who is not an Approver that it waits for one', () => {
    const forCarol = forAlice ? { ...forAlice, you_can_decide: false, why_not: 'not_an_approver' as const } : undefined
    expect(pendingApproverFor(forCarol, DAVE, CAROL, 'Alice')).toEqual({ can: 'nothing', words: 'Asked by Alice. Waiting for an Approver to confirm.' })
  })

  it('tells the person it is about that another Approver must confirm it', () => {
    const daveMe: Me = { id: DAVE.id, display: 'Dave', roles: ['approver'], on_list: true }
    const about = forBob ? { ...forBob, you_can_decide: false, why_not: 'about_you' as const } : undefined
    expect(pendingApproverFor(about, DAVE, daveMe, 'Alice')).toEqual({ can: 'nothing', words: 'Asked by Alice. It’s about you, so another Approver must confirm it.' })
  })

  it('still lets an Approver say not now once the asker is no longer an Operator', () => {
    const gone = forBob ? { ...forBob, you_can_decide: false, why_not: 'asker_gone' as const } : undefined
    expect(pendingApproverFor(gone, DAVE, BOB, 'Alice')).toEqual({ can: 'not_now_only', words: decideRefusalWords.asker_gone })
  })

  it('marks the People tab only for someone who can decide one', () => {
    expect(needsYou(FOR_BOB, 'approver')).toBe(true)
    expect(needsYou(FOR_ALICE, 'approver')).toBe(false)
    expect(needsYou([], 'approver')).toBe(false)
  })

  it('is matched to its person, and an address request is left out', () => {
    const byPerson = approverConfirmationsByPerson(FOR_BOB)
    expect([...byPerson.keys()]).toEqual([DAVE.id])
    expect(byPerson.get(DAVE.id)?.kind).toBe('approver')
  })
})

describe('a decided Approver request', () => {
  const confirmed = personApprover as PersonOut
  const notNow = { ...confirmed, approver: false }

  it('once confirmed, leaves an Approver with nothing waiting', () => {
    expect(confirmed.approver).toBe(true)
    expect(confirmed.pending_approver).toBeNull()
    expect(approverConfirmationsByPerson([]).get(confirmed.id)).toBeUndefined()
    expect(decidedApproverWords('Dave', true)).toBe('Dave is now an Approver.')
  })

  it('after not now, leaves someone who is not an Approver, with nothing waiting', () => {
    expect(notNow.approver).toBe(false)
    expect(notNow.pending_approver).toBeNull()
    expect(decidedApproverWords('Dave', false)).toBe('You said not now, so Dave is not an Approver.')
  })
})

describe('a person who leaves the list while the page is open', () => {
  const GINA = { ...DAVE, id: 'gina', display: 'Gina', email: 'gina@example.test' }
  const HANA = { ...DAVE, id: 'hana', display: 'Hana', email: 'hana@example.test' }
  const IVAN = { ...DAVE, id: 'ivan', display: 'Ivan', email: 'ivan@example.test' }
  const BEFORE = [...PEOPLE, GINA, HANA, IVAN]
  const without = (...ids: string[]) => BEFORE.filter((person) => !ids.includes(person.id))
  const NOTHING: PeopleSaid = { notice: null, problem: null, left: null }

  it('is announced by name when nothing was shown on their row', () => {
    expect(saidAfterListChange(BEFORE, without('ivan'), NOTHING)).toEqual({
      notice: null,
      problem: null,
      left: 'Ivan is no longer on the list. The list now shows who is on it.',
    })
  })

  it('takes the notice that was on their row, and its Undo, and says who left instead', () => {
    const said: PeopleSaid = { notice: { personId: 'hana', words: 'Hana is no longer an Operator.', undo: { name: 'Hana', operator: true } }, problem: null, left: null }
    expect(saidAfterListChange(BEFORE, without('hana'), said)).toEqual({
      notice: null,
      problem: null,
      left: 'Hana is no longer on the list. The list now shows who is on it.',
    })
  })

  it('takes the problem that was on their row, and says who left instead', () => {
    const said: PeopleSaid = { notice: null, problem: { personId: 'gina', words: 'That person is no longer on the list. The list now shows who is on it.' }, left: null }
    expect(saidAfterListChange(BEFORE, without('gina'), said)).toEqual({
      notice: null,
      problem: null,
      left: 'Gina is no longer on the list. The list now shows who is on it.',
    })
  })

  it('keeps a refusal on someone still on the list, and says who left as well', () => {
    const refusal = { personId: 'bob', words: 'At least 2 people must be Approvers, so nobody has to approve their own work.' }
    expect(saidAfterListChange(BEFORE, without('ivan'), { notice: null, problem: refusal, left: null })).toEqual({
      notice: null,
      problem: refusal,
      left: 'Ivan is no longer on the list. The list now shows who is on it.',
    })
  })

  it('keeps a fresh Added message, even before the list shows them, and says who left as well', () => {
    const added = { personId: 'zed', words: 'Added Zed as an Operator.', undo: null }
    const after = [...without('ivan'), { ...DAVE, id: 'zed', display: 'Zed' }]
    expect(saidAfterListChange(BEFORE, after, { notice: added, problem: null, left: null })).toEqual({
      notice: added,
      problem: null,
      left: 'Ivan is no longer on the list. The list now shows who is on it.',
    })
    expect(saidAfterListChange(BEFORE, without('ivan'), { notice: added, problem: null, left: null }).notice).toBe(added)
  })

  it('names everyone who left at once', () => {
    expect(saidAfterListChange(BEFORE, without('gina', 'ivan'), NOTHING).left).toBe('Gina and Ivan are no longer on the list. The list now shows who is on it.')
    expect(leftTheListWords(['Gina', 'Hana', 'Ivan'])).toBe('Gina, Hana and Ivan are no longer on the list. The list now shows who is on it.')
  })

  it('keeps what is shown when nobody left', () => {
    const said: PeopleSaid = { notice: { personId: 'hana', words: 'Hana is no longer an Operator.', undo: { name: 'Hana', operator: true } }, problem: null, left: null }
    expect(saidAfterListChange(BEFORE, [...BEFORE, { ...DAVE, id: 'jo', display: 'Jo' }], said)).toBe(said)
    expect(saidAfterListChange(BEFORE, BEFORE.map((person) => ({ ...person, operator: !person.operator })), said)).toBe(said)
  })
})

describe('who can change settings', () => {
  it('is every Operator, and never an Approver who is not one', () => {
    expect(canChangeSettings(ALICE)).toBe(true)
    expect(canChangeSettings(CAROL)).toBe(true)
    expect(canChangeSettings(BOB)).toBe(false)
    expect(canChangeSettings(undefined)).toBe(false)
  })
})

describe('a person', () => {
  it('who has not signed in yet says so', () => {
    expect(personStatusWords(DAVE)).toBe(NOT_SIGNED_IN_WORDS)
    expect(NOT_SIGNED_IN_WORDS).toBe('Hasn’t signed in yet')
    expect(personStatusWords(PEOPLE[0] as PersonOut)).toBeNull()
  })
})

describe('the settings history', () => {
  const changes = history.changes as SettingsChangeOut[]

  it('names who asked and who decided', () => {
    const lines = historyOf(changes, 'people')
    expect(lines).toHaveLength(4)
    expect(lines[0]?.summary).toBe('Bob confirmed Dave as an Approver, as Alice asked.')
    expect(lines[0]?.who).toBe('Asked by Alice, decided by Bob.')
    expect(lines[1]?.who).toBeNull()
    expect(lines[0]?.when).toBe('Mon 9 Nov, 13:41')
  })

  it('keeps each tab to its own changes', () => {
    expect(historyOf(changes, 'model')).toEqual([])
  })
})

describe('the AI model', () => {
  it('shows only the last 2 characters of a key', () => {
    expect(keyEndingWords('x7')).toBe('API key ending x7')
    expect(keyEndingWords('sk-live-0123456789abcd')).toBe('API key ending cd')
  })

  it('offers the saved key again only at the same address', () => {
    expect(savedKeyFits(ACTIVE, 'https://llm-gateway.aisg.sg')).toBe(true)
    expect(savedKeyFits(ACTIVE, 'https://LLM-gateway.aisg.sg/v1')).toBe(true)
    expect(savedKeyFits(ACTIVE, 'https://api.openai.com/v1')).toBe(false)
    expect(savedKeyFits(ACTIVE, 'not an address')).toBe(false)
    expect(savedKeyFits(null, 'https://llm-gateway.aisg.sg')).toBe(false)
  })

  it('starts on the provider in use', () => {
    const providers = modelActive.providers as Parameters<typeof startingProvider>[0]
    expect(startingProvider(providers, ACTIVE)).toBe('aisg')
    expect(startingProvider(providers, { ...ACTIVE, base_url: 'http://mock-model:8300' })).toBe('other')
    expect(startingProvider(providers, null)).toBe('aisg')
  })

  it('marks its tab for an Operator while no model is connected and nothing waits', () => {
    const empty = modelEmpty as ModelSettingsView
    expect(modelNeedsYou(empty, ALICE)).toBe(true)
    expect(modelNeedsYou(empty, CAROL)).toBe(true)
    expect(modelNeedsYou({ ...empty, you_can_change: false }, BOB)).toBe(false)
    expect(modelNeedsYou({ ...empty, available: false }, ALICE)).toBe(false)
    expect(modelNeedsYou(modelActive as ModelSettingsView, ALICE)).toBe(false)
    expect(modelNeedsYou(undefined, ALICE)).toBe(false)
  })

  it('marks its tab while an address waits only for someone who can decide it, never for the person who entered it', () => {
    const forAlice = { ...(pendingAlice as ModelSettingsView), active: null }
    const forCarol = { ...forAlice, pending: forAlice.pending ? { ...forAlice.pending, why_not: 'Only Approvers can confirm a new address.' } : null }
    const forBob = { ...(pendingBob as ModelSettingsView), active: null }
    expect(modelNeedsYou(forAlice, ALICE)).toBe(false)
    expect(modelNeedsYou(forCarol, CAROL)).toBe(false)
    expect(modelNeedsYou(forBob, BOB)).toBe(true)
    expect(modelNeedsYou(pendingBob as ModelSettingsView, BOB)).toBe(true)
  })

  it('shows a problem beside the field it is about', () => {
    expect(fieldOfProblem('key_refused', 'key', false)).toBe('key')
    expect(fieldOfProblem('unreachable', 'key', true)).toBe('address')
    expect(fieldOfProblem('unreachable', 'key', false)).toBe('form')
    expect(fieldOfProblem('too_slow', 'pick', false)).toBe('model')
  })
})

describe('the tabs', () => {
  it('open on the AI model unless the address names People and roles', () => {
    expect(tabFrom(null)).toBe('model')
    expect(tabFrom('people')).toBe('people')
    expect(tabFrom('nonsense')).toBe('model')
  })
})
