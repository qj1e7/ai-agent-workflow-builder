import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import confirmationsBob from '../../../../contracts/fixtures/people/confirmations.bob.json'
import list from '../../../../contracts/fixtures/people/list.json'
import pendingBob from '../../../../contracts/fixtures/settings/model.pending.bob.json'
import type { ConfirmationOut, Me, PendingModelOut, PersonOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { ConfirmLine } from '../../ui/ConfirmLine'
import { WaitingAddress } from './ModelTab'
import { PersonRow, type RowProps } from './PeopleTab'
import { approverConfirmationsByPerson } from './settings'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'], on_list: true }
const BOB_ME: Me = { id: 'bob', display: 'Bob', roles: ['approver'], on_list: true }
const PEOPLE = list.people as PersonOut[]
const person = (id: string) => {
  const found = PEOPLE.find((one) => one.id === id)
  if (!found) throw new Error(`the people fixture has ${id}`)
  return found
}
const BOB = person('bob')
const CAROL = person('carol')
const DAVE = person('per_01JD4VE')

type Props = Record<string, unknown> & { children?: ReactNode }

function elementsOf(node: ReactNode): ReactElement<Props>[] {
  if (Array.isArray(node)) return node.flatMap((child: ReactNode) => elementsOf(child))
  if (!isValidElement<Props>(node)) return []
  const inside = node.type === ConfirmLine ? ConfirmLine(node.props as unknown as Parameters<typeof ConfirmLine>[0]) : node.props.children
  return [node, ...elementsOf(inside)]
}

const words = (node: ReactNode): string => {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map((child: ReactNode) => words(child)).join('')
  return isValidElement<Props>(node) ? words(node.props.children) : ''
}

const buttonsOf = (node: ReactNode) => elementsOf(node).filter((element) => element.type === Button)
const button = (node: ReactNode, label: string) => {
  const found = buttonsOf(node).find((element) => words(element.props.children) === label)
  if (!found) throw new Error(`no ${label} button`)
  return found
}
const press = (element: ReactElement<Props>) => (element.props['onClick'] as () => void)()
const box = (node: ReactNode, id: string) => {
  const found = elementsOf(node).find((element) => element.type === 'input' && element.props['id'] === id)
  if (!found) throw new Error(`no box ${id}`)
  return { checked: found.props['checked'], change: (checked: boolean) => (found.props['onChange'] as (event: { target: { checked: boolean } }) => void)({ target: { checked } }) }
}
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

function row(over: Partial<RowProps> = {}) {
  const props: RowProps = {
    person: BOB,
    me: ALICE,
    operator: true,
    confirmation: undefined,
    askedByName: 'Alice',
    busy: null,
    problem: null,
    notice: null,
    confirmingRemoval: false,
    onOperator: vi.fn(),
    onApprover: vi.fn(),
    onN8nAccess: vi.fn(),
    onDecide: vi.fn(),
    onAskRemoval: vi.fn(),
    onKeepApprover: vi.fn(),
    ...over,
  }
  return { props, drawn: PersonRow(props) }
}

const QUESTION = 'Remove Bob as an Approver? Another Approver has to confirm before they can approve again.'

describe('removing an Approver asks first, in the row', () => {
  it('sends nothing when the Approver box is unticked, and opens the question', () => {
    const { props, drawn } = row()
    box(drawn, 'person-bob-approver').change(false)
    expect(props.onApprover).not.toHaveBeenCalled()
    expect(props.onAskRemoval).toHaveBeenCalledOnce()
  })

  it('asks in the approved words, with the box still ticked, Keep it first and the destructive Yes last', () => {
    const { drawn } = row({ confirmingRemoval: true })
    expect(text(renderToStaticMarkup(drawn))).toContain(QUESTION)
    expect(box(drawn, 'person-bob-approver').checked).toBe(true)
    const labels = buttonsOf(drawn).map((element) => words(element.props.children))
    expect(labels.slice(-2)).toEqual(['Keep it', 'Yes, remove Approver'])
    expect(button(drawn, 'Yes, remove Approver').props['variant']).toBe('danger-outline')
  })

  it('changes nothing on Keep it', () => {
    const { props, drawn } = row({ confirmingRemoval: true })
    press(button(drawn, 'Keep it'))
    expect(props.onKeepApprover).toHaveBeenCalledOnce()
    expect(props.onApprover).not.toHaveBeenCalled()
  })

  it('removes the Approver role once on Yes', () => {
    const { props, drawn } = row({ confirmingRemoval: true })
    press(button(drawn, 'Yes, remove Approver'))
    expect(props.onApprover).toHaveBeenCalledExactlyOnceWith(false)
    expect(props.onKeepApprover).not.toHaveBeenCalled()
  })

  it('shows no question until the box is unticked', () => {
    expect(text(renderToStaticMarkup(row().drawn))).not.toContain('Remove Bob as an Approver?')
  })

  it('still asks for a new Approver at once when the box is ticked, and changes n8n access at once', () => {
    const { props, drawn } = row({ person: CAROL })
    box(drawn, 'person-carol-approver').change(true)
    expect(props.onApprover).toHaveBeenCalledExactlyOnceWith(true)
    expect(props.onAskRemoval).not.toHaveBeenCalled()
    box(drawn, 'person-carol-n8n').change(false)
    expect(props.onN8nAccess).toHaveBeenCalledExactlyOnceWith(false)
  })
})

describe('Not now', () => {
  it('is the plain secondary button beside the green Confirm on a waiting Approver', () => {
    const confirmation = approverConfirmationsByPerson(confirmationsBob.confirmations as ConfirmationOut[]).get(DAVE.id)
    const { drawn } = row({ person: DAVE, me: BOB_ME, confirmation })
    expect(button(drawn, 'Not now for Dave').props['variant'] ?? 'secondary').toBe('secondary')
    expect(button(drawn, 'Confirm Dave as an Approver').props['variant']).toBe('approve')
  })

  it('is the plain secondary button beside Confirm address on a waiting model address', () => {
    const drawn = WaitingAddress({ pending: pendingBob.pending as PendingModelOut, active: null, pressed: null, problem: null, onDecide: vi.fn() })
    expect(button(drawn, 'Not now').props['variant'] ?? 'secondary').toBe('secondary')
    expect(button(drawn, 'Confirm address').props['variant']).toBe('approve')
  })
})
