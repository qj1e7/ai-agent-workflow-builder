import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useCacheScope } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddPerson, useAskApprover, useConfirmations, useDecideConfirmation, usePeopleList, useRemoveApprover, useSetOperator } from '../../api/settingsQueries'
import type { ConfirmationOut, Me, PersonOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { focusIfFocusFell } from '../../ui/focus'
import { personTone } from '../../ui/personTone'
import { ClockMark, ShieldMark } from './marks'
import {
  addedWords,
  approverConfirmationsByPerson,
  approverRemovedWords,
  askedApproverWords,
  canChangeSettings,
  decidedApproverWords,
  ONLY_OPERATORS_WORDS,
  operatorChangeWords,
  peopleRefusalOf,
  pendingApproverFor,
  personStatusWords,
  ROLE_RULES,
  saidAfterListChange,
  saidAfterRefusal,
  undoneWords,
  type PeopleNotice,
  type PeopleSaid,
} from './settings'
import { FieldError, History, useFocusOnNextRender, useSettingsWords } from './SettingsParts'
import styles from './Settings.module.css'

const NOTICE_ID = 'people-notice'
const PROBLEM_ID = 'people-problem'
const LEFT_ID = 'people-left'
export const PEOPLE_LEAD = 'Operators set up workflows and change settings. Approvers say yes or no to changes. People sign in with their NCS account.'

const operatorBoxId = (personId: string) => `person-${personId}-operator`
const approverBoxId = (personId: string) => `person-${personId}-approver`
const rowErrorId = (personId: string) => `person-${personId}-error`

const NOTHING_SAID: PeopleSaid = { notice: null, problem: null, left: null }

interface Settled {
  readonly onSuccess: () => void
  readonly onError: (error: unknown) => void
  readonly onSettled: () => void
}

interface Busy {
  readonly personId: string
  readonly act: 'operator' | 'approver' | 'confirm' | 'not_now' | 'undo'
  readonly to?: boolean
}

export function PeopleTab({ me }: { me: Me | undefined }) {
  const people = usePeopleList()
  const confirmations = useConfirmations()
  const words = useSettingsWords()
  const viewer = useCacheScope()
  if (people.isPending) {
    return (
      <section className={styles['panel']} aria-label="People and roles">
        <p className="muted" role="status">
          Loading
        </p>
      </section>
    )
  }
  if (people.isError) {
    return (
      <section className={styles['panel']} aria-label="People and roles">
        <p role="status">{words(people.error)}</p>
        <div className={styles['buttons']}>
          <Button onClick={() => void people.refetch()}>Try again</Button>
        </div>
      </section>
    )
  }
  return <PeoplePanel key={viewer} people={people.data} confirmations={confirmations.data} me={me} />
}

interface PanelProps {
  people: readonly PersonOut[]
  confirmations: readonly ConfirmationOut[] | undefined
  me: Me | undefined
}

function PeoplePanel({ people, confirmations, me }: PanelProps) {
  const words = useSettingsWords()
  const operator = canChangeSettings(me)
  const setOperator = useSetOperator()
  const askApprover = useAskApprover()
  const removeApprover = useRemoveApprover()
  const decide = useDecideConfirmation()
  const latch = useLatch()
  const focus = useFocusOnNextRender()
  const [said, setSaid] = useState<PeopleSaid>(NOTHING_SAID)
  const [listed, setListed] = useState(people)
  const [busy, setBusy] = useState<Busy | null>(null)
  if (listed !== people) {
    setListed(people)
    setSaid(saidAfterListChange(listed, people, said))
  }
  const { notice, problem, left } = said
  const tell = (next: PeopleNotice) => setSaid((now) => ({ notice: next, problem: null, left: now.left }))

  const waiting = approverConfirmationsByPerson(confirmations)
  const names = new Map(people.map((person) => [person.id, person.display]))
  const noticeHasRow = notice !== null && people.some((person) => person.id === notice.personId)
  // A row that left the list takes its own error with it, so that error moves to the page.
  const problemLostRow = problem !== null && !people.some((person) => person.id === problem.personId)
  useEffect(() => {
    if (problemLostRow) document.getElementById(PROBLEM_ID)?.focus()
  }, [problemLostRow])
  // When the focused row is the one that left, focus would fall to the page body, so the line that says so takes it.
  useEffect(() => {
    if (left) focusIfFocusFell(LEFT_ID)
  }, [left])

  function change(person: PersonOut, act: Busy['act'], to: boolean | undefined, send: (done: Settled) => void, after: () => void) {
    latch.run((settled) => {
      setBusy(to === undefined ? { personId: person.id, act } : { personId: person.id, act, to })
      setSaid((now) => ({ notice: now.notice, problem: null, left: null }))
      send({
        onSuccess: after,
        onError: (error) => {
          const why = words(error, act === 'confirm' || act === 'not_now' ? 'confirmation' : 'person', person.display)
          setSaid((now) => saidAfterRefusal(now, { personId: person.id, words: why }))
        },
        onSettled: () => {
          setBusy(null)
          settled()
        },
      })
    })
  }

  function onOperator(person: PersonOut, to: boolean) {
    change(person, 'operator', to, (done) => setOperator.mutate({ personId: person.id, operator: to }, done), () =>
      tell({ personId: person.id, words: operatorChangeWords(person.display, to), undo: { name: person.display, operator: !to } }),
    )
  }

  function onUndo(person: PersonOut, undo: NonNullable<PeopleNotice['undo']>) {
    change(person, 'undo', undefined, (done) => setOperator.mutate({ personId: person.id, operator: undo.operator }, done), () => {
      tell({ personId: person.id, words: undoneWords(undo.name, undo.operator), undo: null })
      focus(operatorBoxId(person.id))
    })
  }

  function onApprover(person: PersonOut, to: boolean) {
    change(person, 'approver', to, (done) => (to ? askApprover.mutate(person.id, done) : removeApprover.mutate(person.id, done)), () => {
      tell({ personId: person.id, words: to ? askedApproverWords(person.display) : approverRemovedWords(person.display), undo: null })
      // The box is disabled while the request waits, so focus would otherwise fall to the page.
      focus(NOTICE_ID)
    })
  }

  function onDecide(person: PersonOut, confirmation: ConfirmationOut, verdict: 'confirm' | 'not_now') {
    change(person, verdict, undefined, (done) => decide.mutate({ confirmationId: confirmation.confirmation_id, verdict, digest: confirmation.digest }, done), () => {
      tell({ personId: person.id, words: decidedApproverWords(person.display, verdict === 'confirm'), undo: null })
      focus(NOTICE_ID)
    })
  }

  function onAdded(person: PersonOut, askedApprover: boolean) {
    tell({ personId: person.id, words: addedWords(person.display, askedApprover), undo: null })
    focus(NOTICE_ID)
  }

  function noticeFor(person: PersonOut | null) {
    if (!notice) return null
    const undo = notice.undo
    return (
      <div id={NOTICE_ID} tabIndex={-1} className={styles['said']}>
        <span>{notice.words}</span>
        {undo && person && operator ? (
          <Button loading={busy?.act === 'undo'} onClick={() => onUndo(person, undo)}>
            Undo
          </Button>
        ) : null}
      </div>
    )
  }

  return (
    <section className={styles['panel']} aria-labelledby="people-heading">
      <h2 id="people-heading">People and roles</h2>
      <p className={styles['note']}>{PEOPLE_LEAD}</p>
      {operator ? null : <p className={styles['note']}>{ONLY_OPERATORS_WORDS}</p>}
      <p className="visually-hidden" role="status">
        {problem?.words ?? notice?.words ?? ''}
      </p>
      <p className="visually-hidden" role="status">
        {left?.words ?? ''}
      </p>
      {left ? (
        <div id={LEFT_ID} tabIndex={-1} className={styles['said']}>
          <span>{left.words}</span>
        </div>
      ) : null}
      {notice && !noticeHasRow ? noticeFor(null) : null}
      {problemLostRow ? (
        <div id={PROBLEM_ID} tabIndex={-1}>
          <FieldError id={rowErrorId(problem.personId)} words={problem.words} />
        </div>
      ) : null}
      <ul className={styles['people']} aria-label="People on the list">
        {people.map((person) => (
          <PersonRow
            key={person.id}
            person={person}
            me={me}
            operator={operator}
            confirmation={waiting.get(person.id)}
            askedByName={names.get(person.pending_approver?.asked_by ?? '') ?? 'an Operator'}
            busy={busy?.personId === person.id ? busy : null}
            problem={problem?.personId === person.id ? problem.words : null}
            notice={notice?.personId === person.id ? noticeFor(person) : null}
            onOperator={(to) => onOperator(person, to)}
            onApprover={(to) => onApprover(person, to)}
            onDecide={(confirmation, verdict) => onDecide(person, confirmation, verdict)}
          />
        ))}
      </ul>
      <ul className={styles['rules']} aria-label="The rules">
        {ROLE_RULES.map((rule) => (
          <li key={rule}>
            <ShieldMark />
            <span>{rule}</span>
          </li>
        ))}
      </ul>
      {operator ? <AddPerson onAdded={onAdded} /> : null}
      <History area="people" />
    </section>
  )
}

interface RowProps {
  person: PersonOut
  me: Me | undefined
  operator: boolean
  confirmation: ConfirmationOut | undefined
  askedByName: string
  busy: Busy | null
  problem: string | null
  notice: ReactNode
  onOperator: (to: boolean) => void
  onApprover: (to: boolean) => void
  onDecide: (confirmation: ConfirmationOut, verdict: 'confirm' | 'not_now') => void
}

function PersonRow({ person, me, operator, confirmation, askedByName, busy, problem, notice, onOperator, onApprover, onDecide }: RowProps) {
  const tone = personTone(person.display)
  const status = personStatusWords(person)
  const pending = person.pending_approver !== null
  const operatorTicked = busy?.act === 'operator' && busy.to !== undefined ? busy.to : person.operator
  const approverTicked = busy?.act === 'approver' && busy.to !== undefined ? busy.to : person.approver || pending
  const describedBy = problem ? rowErrorId(person.id) : undefined
  const can = pending ? pendingApproverFor(confirmation, person, me, confirmation?.asked_by_name ?? askedByName) : null

  return (
    <li className={styles['person']}>
      <span className={styles['initial']} style={{ background: tone.bg, color: tone.ink }} aria-hidden="true">
        {person.display.charAt(0)}
      </span>
      <div className={styles['who']}>
        <b>
          {person.display}
          {me?.id === person.id ? <span className={styles['tag']}>You</span> : null}
        </b>
        <span className={styles['small']}>{person.email}</span>
        {status ? <span className={styles['small']}>{status}</span> : null}
      </div>
      <div className={styles['roles']}>
        <label className={styles['check']}>
          <input
            type="checkbox"
            id={operatorBoxId(person.id)}
            checked={operatorTicked}
            disabled={!operator}
            aria-describedby={describedBy}
            onChange={(event) => onOperator(event.target.checked)}
          />
          Operator<span className="visually-hidden"> for {person.display}</span>
        </label>
        <label className={styles['check']}>
          <input
            type="checkbox"
            id={approverBoxId(person.id)}
            checked={approverTicked}
            disabled={!operator || pending}
            aria-describedby={describedBy}
            onChange={(event) => onApprover(event.target.checked)}
          />
          Approver<span className="visually-hidden"> for {person.display}</span>
        </label>
      </div>
      {pending ? (
        <div className={styles['rowNote']}>
          <span className={styles['pill']} data-tone="wait">
            <ClockMark size={12} />
            Approver: waiting for another Approver to confirm
          </span>
          {can && can.can !== 'decide' ? <span className={styles['small']}>{can.words}</span> : null}
          {confirmation && (can?.can === 'decide' || can?.can === 'not_now_only') ? (
            <span className={styles['buttons']}>
              <Button variant="danger-outline" loading={busy?.act === 'not_now'} onClick={() => onDecide(confirmation, 'not_now')}>
                Not now<span className="visually-hidden"> for {person.display}</span>
              </Button>
              {can.can === 'decide' ? (
                <Button variant="approve" loading={busy?.act === 'confirm'} onClick={() => onDecide(confirmation, 'confirm')}>
                  Confirm<span className="visually-hidden"> {person.display} as an Approver</span>
                </Button>
              ) : null}
            </span>
          ) : null}
        </div>
      ) : null}
      {problem ? (
        <div className={styles['rowNote']}>
          <FieldError id={rowErrorId(person.id)} words={problem} />
        </div>
      ) : null}
      {notice ? <div className={styles['rowNote']}>{notice}</div> : null}
    </li>
  )
}

type AddField = 'email' | 'display' | 'roles' | 'form'

const ADD_IDS: Record<AddField, string> = { email: 'add-email', display: 'add-name', roles: 'add-operator', form: 'add-submit' }
const addErrorId = (field: AddField) => `add-${field}-error`

function AddPerson({ onAdded }: { onAdded: (person: PersonOut, askedApprover: boolean) => void }) {
  const words = useSettingsWords()
  const add = useAddPerson()
  const latch = useLatch()
  const focus = useFocusOnNextRender()
  const [email, setEmail] = useState('')
  const [display, setDisplay] = useState('')
  const [operator, setOperator] = useState(true)
  const [approver, setApprover] = useState(false)
  const [errors, setErrors] = useState<Partial<Record<AddField, string>>>({})

  function fail(next: Partial<Record<AddField, string>>) {
    setErrors(next)
    const first = (['email', 'display', 'roles', 'form'] as const).find((field) => next[field])
    if (first) focus(ADD_IDS[first])
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const problems: Partial<Record<AddField, string>> = {}
    if (!email.trim()) problems.email = 'Type the person’s work email.'
    if (!display.trim()) problems.display = 'Type the person’s name.'
    if (!operator && !approver) problems.roles = 'Choose at least one role.'
    if (Object.keys(problems).length > 0) {
      fail(problems)
      return
    }
    latch.run((settled) => {
      setErrors({})
      add.mutate(
        { email: email.trim(), display: display.trim(), operator, approver },
        {
          onSuccess: (person) => {
            setEmail('')
            setDisplay('')
            setOperator(true)
            setApprover(false)
            onAdded(person, approver)
          },
          onError: (error) => {
            const refusal = peopleRefusalOf(error)
            const said = words(error)
            if (refusal === 'bad_email' || refusal === 'already_on_the_list') fail({ email: said })
            else if (refusal === 'no_role') fail({ roles: said })
            else fail({ form: said })
          },
          onSettled: settled,
        },
      )
    })
  }

  const describe = (field: AddField) => (errors[field] ? addErrorId(field) : undefined)

  return (
    <form className={styles['form']} onSubmit={onSubmit} noValidate aria-labelledby="add-heading">
      <h3 id="add-heading">Add a person</h3>
      <div className={styles['grid']}>
        <div className={styles['field']}>
          <label htmlFor={ADD_IDS.email}>Work email</label>
          <input
            id={ADD_IDS.email}
            className={styles['input']}
            type="email"
            inputMode="email"
            autoComplete="off"
            spellCheck={false}
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={describe('email')}
          />
          <FieldError id={addErrorId('email')} words={errors.email} />
        </div>
        <div className={styles['field']}>
          <label htmlFor={ADD_IDS.display}>Name</label>
          <input
            id={ADD_IDS.display}
            className={styles['input']}
            type="text"
            autoComplete="off"
            maxLength={120}
            value={display}
            onChange={(event) => setDisplay(event.target.value)}
            aria-invalid={errors.display ? true : undefined}
            aria-describedby={describe('display')}
          />
          <FieldError id={addErrorId('display')} words={errors.display} />
        </div>
      </div>
      <fieldset className={styles['fieldset']} aria-describedby={['add-roles-help', describe('roles')].filter(Boolean).join(' ')}>
        <legend>Roles</legend>
        <div className={styles['roles']}>
          <label className={styles['check']}>
            <input id={ADD_IDS.roles} type="checkbox" checked={operator} onChange={(event) => setOperator(event.target.checked)} />
            Operator
          </label>
          <label className={styles['check']}>
            <input type="checkbox" checked={approver} onChange={(event) => setApprover(event.target.checked)} />
            Approver
          </label>
        </div>
        <span className={styles['help']} id="add-roles-help">
          The Approver role starts once another Approver confirms it.
        </span>
        <FieldError id={addErrorId('roles')} words={errors.roles} />
      </fieldset>
      <div className={styles['buttons']}>
        <Button id={ADD_IDS.form} type="submit" variant="primary" loading={add.isPending}>
          Add
        </Button>
      </div>
      <FieldError id={addErrorId('form')} words={errors.form} />
    </form>
  )
}
