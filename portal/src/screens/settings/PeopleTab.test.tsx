import { beforeEach, describe, expect, it, vi } from 'vitest'
import confirmationsBob from '../../../../contracts/fixtures/people/confirmations.bob.json'
import list from '../../../../contracts/fixtures/people/list.json'
import pendingBob from '../../../../contracts/fixtures/settings/model.pending.bob.json'
import type { ConfirmationOut, Me, PendingModelOut, PersonOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { ConfirmLine } from '../../ui/ConfirmLine'
import { testHooks } from '../../ui/testHooks'
import { buttonIn, elementsOf, press, pressKey, wordsOf, type Drawn } from '../../ui/testing'
import { WaitingAddress } from './ModelTab'
import { PeoplePanel, PersonRow, type RowProps } from './PeopleTab'
import { approverConfirmationsByPerson } from './settings'

vi.mock('react', async (importOriginal) => (await import('../../ui/testHooks')).withTestHooks(await importOriginal<object>()))

interface Answers {
  readonly onSuccess?: () => void
  readonly onError?: (error: unknown) => void
  readonly onSettled?: () => void
}

/** What the panel asked the platform for, in order, and how to answer each. */
const platform = vi.hoisted(() => ({ sent: [] as string[], answers: [] as Answers[], focused: [] as string[] }))

vi.mock('../../api/settingsQueries', async (importOriginal) => {
  const mutation = (name: string) => () => ({
    isPending: false,
    mutate: (input: unknown, answers: Answers) => {
      platform.sent.push(`${name} ${JSON.stringify(input)}`)
      platform.answers.push(answers)
    },
  })
  return {
    ...(await importOriginal<object>()),
    useSetOperator: mutation('operator'),
    useAskApprover: mutation('ask approver'),
    useRemoveApprover: mutation('remove approver'),
    useSetN8nAccess: mutation('n8n access'),
    useDecideConfirmation: mutation('decide'),
  }
})

vi.mock('./SettingsParts', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useFocusOnNextRender: () => (id: string) => platform.focused.push(id),
  useSettingsWords: () => () => 'The platform said no.',
}))

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'], on_list: true }
const BOB_ME: Me = { id: 'bob', display: 'Bob', roles: ['approver'], on_list: true }
const PEOPLE = list.people as PersonOut[]
const person = (id: string) => {
  const found = PEOPLE.find((one) => one.id === id)
  if (!found) throw new Error(`the people fixture has ${id}`)
  return found
}
const DAVE = person('per_01JD4VE')
const withBob = (change: Partial<PersonOut>) => PEOPLE.map((one) => (one.id === 'bob' ? { ...one, ...change } : one))

const QUESTION = 'Remove Bob as an Approver? Another Approver has to confirm before they can approve again.'
const BOB_BOX = 'person-bob-approver'
const DRAWN_OUT = [PersonRow, ConfirmLine, Button]

function panel(people: readonly PersonOut[] = PEOPLE): Drawn[] {
  return elementsOf(
    testHooks.draw(() => PeoplePanel({ people, confirmations: [], me: ALICE })),
    DRAWN_OUT,
  )
}

function rowOf(elements: readonly Drawn[], name: string): Drawn[] {
  const row = elements.find((element) => element.type === PersonRow && (element.props['person'] as PersonOut).display === name)
  if (!row) throw new Error(`no row for ${name}`)
  return elementsOf(row, DRAWN_OUT)
}

function box(elements: readonly Drawn[], id: string) {
  const found = elements.find((element) => element.type === 'input' && element.props['id'] === id)
  if (!found) throw new Error(`no box ${id}`)
  return {
    checked: found.props['checked'],
    change: (checked: boolean) => (found.props['onChange'] as (event: { target: { checked: boolean } }) => void)({ target: { checked } }),
  }
}

const questionIn = (elements: readonly Drawn[]) => elements.find((element) => element.props['role'] === 'group')
const untickBob = () => box(panel(), BOB_BOX).change(false)

beforeEach(() => {
  testHooks.reset()
  platform.sent.length = 0
  platform.answers.length = 0
  platform.focused.length = 0
})

describe('removing an Approver on People and permissions', () => {
  it('sends nothing when the Approver box is unticked, and asks in the row with the box still ticked', () => {
    untickBob()
    expect(platform.sent).toEqual([])
    const bob = rowOf(panel(), 'Bob')
    expect(wordsOf(questionIn(bob))).toContain(QUESTION)
    expect(box(bob, BOB_BOX).checked).toBe(true)
  })

  it('draws the question as a group described by its sentence, Keep it first with focus, and the destructive Yes last', () => {
    untickBob()
    const bob = rowOf(panel(), 'Bob')
    const group = questionIn(bob)
    expect(group?.props['aria-label']).toBe('Remove Bob as an Approver')
    const sentence = bob.find((element) => element.props['id'] === group?.props['aria-describedby'])
    expect(wordsOf(sentence)).toBe(QUESTION)
    const labels = bob.filter((element) => element.type === 'button').map((element) => wordsOf(element))
    expect(labels.slice(-2)).toEqual(['Keep it', 'Yes, remove Approver'])
    expect(buttonIn(bob, 'Yes, remove Approver').props['className']).toMatch(/dangerOutline/)
    const keep = { focus: vi.fn() }
    ;(buttonIn(bob, 'Keep it').props['ref'] as (button: typeof keep) => void)(keep)
    expect(keep.focus).toHaveBeenCalledOnce()
  })

  it('changes nothing on Keep it, and gives focus back to the box', () => {
    untickBob()
    press(buttonIn(rowOf(panel(), 'Bob'), 'Keep it'))
    expect(platform.sent).toEqual([])
    expect(platform.focused).toEqual([BOB_BOX])
    expect(questionIn(rowOf(panel(), 'Bob'))).toBeUndefined()
  })

  it('changes nothing on Escape, from either button', () => {
    for (const label of ['Keep it', 'Yes, remove Approver']) {
      untickBob()
      expect(pressKey(buttonIn(rowOf(panel(), 'Bob'), label), 'Escape').prevented).toBe(true)
      expect(questionIn(rowOf(panel(), 'Bob'))).toBeUndefined()
    }
    expect(platform.sent).toEqual([])
  })

  it('removes the role once on Yes, even pressed twice, with focus back on the box while it is sent', () => {
    untickBob()
    const yes = buttonIn(rowOf(panel(), 'Bob'), 'Yes, remove Approver')
    press(yes)
    press(yes)
    expect(platform.sent).toEqual(['remove approver "bob"'])
    expect(platform.focused).toEqual([BOB_BOX])
    const bob = rowOf(panel(), 'Bob')
    expect(questionIn(bob)).toBeUndefined()
    expect(box(bob, BOB_BOX).checked).toBe(false)
  })

  it('closes the question when a read shows they are no longer an Approver, and keeps it closed after', () => {
    untickBob()
    expect(questionIn(rowOf(panel(withBob({ approver: false })), 'Bob'))).toBeUndefined()
    expect(questionIn(rowOf(panel(withBob({ approver: true })), 'Bob'))).toBeUndefined()
  })

  it('holds Yes as busy while another row’s change is on its way, and sends it once that one settles', () => {
    box(panel(), 'person-carol-operator').change(false)
    untickBob()
    const busy = buttonIn(rowOf(panel(), 'Bob'), 'Yes, remove Approver')
    expect(busy.props['aria-busy']).toBe(true)
    press(busy)
    expect(platform.sent).toEqual(['operator {"personId":"carol","operator":false}'])
    expect(questionIn(rowOf(panel(), 'Bob'))).toBeDefined()

    platform.answers[0]?.onSuccess?.()
    platform.answers[0]?.onSettled?.()
    press(buttonIn(rowOf(panel(), 'Bob'), 'Yes, remove Approver'))
    expect(platform.sent).toEqual(['operator {"personId":"carol","operator":false}', 'remove approver "bob"'])
  })

  it('still asks for a new Approver at once when the box is ticked', () => {
    box(panel(), 'person-carol-approver').change(true)
    expect(platform.sent).toEqual(['ask approver "carol"'])
    expect(questionIn(rowOf(panel(), 'Carol'))).toBeUndefined()
  })
})

describe('Not now', () => {
  const variantOf = (drawn: Drawn[], label: string) => {
    const button = drawn.find((element) => element.type === Button && wordsOf(element) === label)
    if (!button) throw new Error(`no ${label} button`)
    return button.props['variant'] ?? 'secondary'
  }

  it('is the plain secondary button beside the green Confirm on a waiting Approver', () => {
    const props: RowProps = {
      person: DAVE,
      me: BOB_ME,
      operator: false,
      confirmation: approverConfirmationsByPerson(confirmationsBob.confirmations as ConfirmationOut[]).get(DAVE.id),
      askedByName: 'Alice',
      busy: null,
      changeInFlight: false,
      problem: null,
      notice: null,
      confirmingRemoval: false,
      onOperator: vi.fn(),
      onApprover: vi.fn(),
      onN8nAccess: vi.fn(),
      onDecide: vi.fn(),
      onAskRemoval: vi.fn(),
      onKeepApprover: vi.fn(),
    }
    const drawn = elementsOf(PersonRow(props), [])
    expect(variantOf(drawn, 'Not now for Dave')).toBe('secondary')
    expect(variantOf(drawn, 'Confirm Dave as an Approver')).toBe('approve')
  })

  it('is the plain secondary button beside Confirm address on a waiting model address', () => {
    const drawn = elementsOf(WaitingAddress({ pending: pendingBob.pending as PendingModelOut, active: null, pressed: null, problem: null, onDecide: vi.fn() }), [])
    expect(variantOf(drawn, 'Not now')).toBe('secondary')
    expect(variantOf(drawn, 'Confirm address')).toBe('approve')
  })
})
