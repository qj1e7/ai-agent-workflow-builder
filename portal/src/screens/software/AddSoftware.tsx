import { useEffect, useReducer, useRef, type FormEvent, type ReactNode, type RefObject } from 'react'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddSoftware, useFindSoftware } from '../../api/queries'
import { Button } from '../../ui/Button'
import { IconExternal } from '../../ui/icons'
import { addReducer, alreadyWords, matchesOf, modeOf, readyToAdd, releaseWords, START, type AddAction, type AddState } from './addByName'
import { addProblems, checkName, REPO_HELP, VERSION_HELP } from './software'
import styles from './Software.module.css'

function Field({ id, label, optional, help, error, children }: { id: string; label: string; optional?: boolean; help: string; error: string | undefined; children: ReactNode }) {
  return (
    <div className={styles['field']}>
      <label htmlFor={id}>
        {label}
        {optional ? <span className="muted"> (optional)</span> : null}
      </label>
      {children}
      {error ? (
        <p className={styles['error']} id={`${id}-error`}>
          {error}
        </p>
      ) : (
        <p className={styles['help']} id={`${id}-help`}>
          {help}
        </p>
      )}
    </div>
  )
}

interface FormProps {
  readonly state: AddState
  readonly busy: boolean
  readonly refs?: { readonly name?: RefObject<HTMLInputElement | null>; readonly repo?: RefObject<HTMLInputElement | null>; readonly version?: RefObject<HTMLInputElement | null> } | undefined
  readonly dispatch?: ((action: AddAction) => void) | undefined
  readonly onSubmit?: ((event: FormEvent<HTMLFormElement>) => void) | undefined
  readonly onTypeAddress?: (() => void) | undefined
}

const describedBy = (id: string, error: string | undefined) => (error ? `${id}-error` : `${id}-help`)

function VersionField({ state, refs, dispatch }: Pick<FormProps, 'state' | 'refs' | 'dispatch'>) {
  const error = state.errors.version
  return (
    <Field id="sw-version" label="Version we run" optional help={VERSION_HELP} error={error}>
      <input
        id="sw-version"
        ref={refs?.version}
        type="text"
        value={state.version}
        placeholder="1.2.14"
        autoComplete="off"
        inputMode="decimal"
        spellCheck={false}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy('sw-version', error)}
        onChange={(event) => dispatch?.({ type: 'typed', field: 'version', value: event.target.value })}
      />
    </Field>
  )
}

function NameStep({ state, busy, refs, dispatch, onTypeAddress }: FormProps) {
  const error = state.errors.name
  return (
    <>
      <h3 id="add-software-heading">Add software</h3>
      <Field id="sw-name" label="Software name" help="Type the name, such as Kubernetes. I’ll find its GitHub project." error={error}>
        <input
          id="sw-name"
          ref={refs?.name}
          type="text"
          value={state.name}
          maxLength={80}
          autoComplete="off"
          placeholder="Kubernetes"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy('sw-name', error)}
          onChange={(event) => dispatch?.({ type: 'typed', field: 'name', value: event.target.value })}
        />
      </Field>
      {state.errors.form ? (
        <p className={styles['error']} role="alert">
          {state.errors.form}
        </p>
      ) : null}
      <div className={styles['formActions']}>
        <Button type="submit" variant="primary" loading={busy}>
          Find it
        </Button>
        <Button onClick={onTypeAddress}>I have the GitHub address</Button>
      </div>
    </>
  )
}

function Guess({ state, dispatch }: Pick<FormProps, 'state' | 'dispatch'>) {
  const matches = matchesOf(state)
  const mode = modeOf(state)
  const answer = state.answer
  if (mode === 'single') {
    const match = matches[0]
    if (!match) return null
    return (
      <>
        <p className={styles['guess']}>
          <b>
            <a href={`https://github.com/${match.repo}`} target="_blank" rel="noopener noreferrer">
              {match.repo}
              <IconExternal size={12} />
              <span className="visually-hidden"> (opens GitHub in a new tab)</span>
            </a>
          </b>
          <span className="muted"> {match.what}.</span>
        </p>
        <ul className={styles['why']}>
          <li>{match.why}</li>
          <li>{releaseWords(match)}</li>
          {match.already_listed ? <li role="status">{alreadyWords(match.repo, match.already_listed)}</li> : null}
        </ul>
      </>
    )
  }
  if (mode === 'choose') {
    return (
      <fieldset className={styles['pick']} aria-describedby={state.errors.form ? 'sw-form-error' : undefined}>
        <legend>Which one do you mean?</legend>
        {matches.map((match, index) => (
          <div key={match.repo} className={styles['pickRow']}>
            <input id={`sw-pick-${index}`} type="radio" name="sw-pick" value={index} checked={state.pick === index} onChange={() => dispatch?.({ type: 'picked', index })} />
            <label htmlFor={`sw-pick-${index}`}>
              <b>{match.repo}</b>
              <span className="muted">
                {' '}
                {match.what}. {match.why} {releaseWords(match)}
                {match.already_listed ? ` ${alreadyWords(match.repo, match.already_listed)}` : ''}
              </span>
            </label>
          </div>
        ))}
      </fieldset>
    )
  }
  const lead =
    state.change || answer === null
      ? 'You’re choosing the project yourself.'
      : answer.status === 'found'
        ? ''
        : answer.message
  return lead ? (
    <p role={answer?.status === 'not_checked' ? 'alert' : 'status'} className={answer && answer.status !== 'found' ? styles['noMatch'] : 'muted'}>
      {lead}
    </p>
  ) : null
}

function GuessStep({ state, busy, refs, dispatch }: FormProps) {
  const mode = modeOf(state)
  const typed = state.name.trim()
  const unmatched = mode === 'address' && !state.change && state.answer !== null
  const heading = unmatched ? `I couldn’t find “${typed}”` : `Adding ${typed}`
  const repoError = state.errors.repo
  const addLabel = mode === 'single' ? 'Looks right, add it' : `Add ${typed}`
  return (
    <>
      <h3 id="sw-guess" tabIndex={-1}>
        {heading}
      </h3>
      <Guess state={state} dispatch={dispatch} />
      {mode === 'address' ? (
        <Field id="sw-repo" label="GitHub repository" help={REPO_HELP} error={repoError}>
          <input
            id="sw-repo"
            ref={refs?.repo}
            type="text"
            value={state.repo}
            placeholder="owner/name"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            aria-invalid={repoError ? true : undefined}
            aria-describedby={describedBy('sw-repo', repoError)}
            onChange={(event) => dispatch?.({ type: 'typed', field: 'repo', value: event.target.value })}
          />
        </Field>
      ) : null}
      <VersionField state={state} refs={refs} dispatch={dispatch} />
      {state.errors.form ? (
        <p className={styles['error']} id="sw-form-error" role="alert">
          {state.errors.form}
        </p>
      ) : null}
      <div className={styles['formActions']}>
        <Button type="submit" variant="primary" loading={busy}>
          {addLabel}
        </Button>
        {mode === 'single' ? <Button onClick={() => dispatch?.({ type: 'change' })}>Change</Button> : null}
        {mode === 'choose' ? <Button onClick={() => dispatch?.({ type: 'change' })}>None of these</Button> : null}
        <Button onClick={() => dispatch?.({ type: 'reset' })}>Start again</Button>
      </div>
    </>
  )
}

export function AddSoftwareForm(props: FormProps) {
  return (
    <form className={styles['addForm']} onSubmit={props.onSubmit} noValidate aria-labelledby={props.state.step === 'name' ? 'add-software-heading' : 'sw-guess'}>
      {props.state.step === 'name' ? <NameStep {...props} /> : <GuessStep {...props} />}
    </form>
  )
}

function focusTarget(state: AddState): string | null {
  if (state.errors.name) return 'sw-name'
  if (state.errors.repo) return 'sw-repo'
  if (state.errors.version) return 'sw-version'
  if (state.errors.form) return 'sw-form-error'
  return null
}

export function AddSoftware({ names, repos, onAdded }: { names: readonly string[]; repos: readonly string[]; onAdded: (name: string) => void }) {
  const [state, dispatch] = useReducer(addReducer, START)
  const find = useFindSoftware()
  const add = useAddSoftware()
  const sending = useLatch()
  const words = useErrorWords()
  const refs = { name: useRef<HTMLInputElement>(null), repo: useRef<HTMLInputElement>(null), version: useRef<HTMLInputElement>(null) }
  const moved = useRef(state.step)

  // Focus follows the form: the guess heading when the finder answers, the name when the form starts again, and the first problem.
  useEffect(() => {
    const target = focusTarget(state)
    if (target) {
      document.getElementById(target)?.focus()
    } else if (moved.current !== state.step) {
      document.getElementById(state.step === 'guess' ? (state.change && state.answer === null ? 'sw-repo' : 'sw-guess') : 'sw-name')?.focus()
    }
    moved.current = state.step
  }, [state])

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (state.step === 'name') {
      const name = checkName(state.name, names)
      if (!name.ok) return dispatch({ type: 'refused', errors: { name: name.words } })
      sending.run((settled) =>
        find.mutate(name.value, {
          onSuccess: (answer) => dispatch({ type: 'answered', answer }),
          onError: (error) => dispatch({ type: 'refused', errors: addProblems(error) ?? { form: words(error) } }),
          onSettled: settled,
        }),
      )
      return
    }
    const ready = readyToAdd(state, names, repos)
    if (!ready.ok) return dispatch({ type: 'refused', errors: ready.errors })
    sending.run((settled) =>
      add.mutate(ready.body, {
        onSuccess: () => {
          dispatch({ type: 'reset' })
          onAdded(ready.body.name)
        },
        onError: (error) => {
          const refused = addProblems(error)
          if (error instanceof ApiError && error.status === 409) {
            dispatch({ type: 'refused', errors: modeOf(state) === 'address' ? { repo: `${ready.body.repo} is already on the list.` } : { form: `${ready.body.repo} is already on the list.` } })
          } else dispatch({ type: 'refused', errors: refused ?? { form: words(error) } })
        },
        onSettled: settled,
      }),
    )
  }

  function typeAddress() {
    const name = checkName(state.name, names)
    dispatch(name.ok ? { type: 'typeAddress' } : { type: 'refused', errors: { name: name.words } })
  }

  return <AddSoftwareForm state={state} busy={find.isPending || add.isPending} refs={refs} dispatch={dispatch} onSubmit={submit} onTypeAddress={typeAddress} />
}
