import { useEffect, useReducer, useRef, type FormEvent, type ReactNode, type RefObject } from 'react'
import { ApiError } from '../../api/client'
import type { WatchedSoftwareView } from '../../api/types'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddSoftware, useFindSoftware } from '../../api/queries'
import { Button } from '../../ui/Button'
import { IconExternal } from '../../ui/icons'
import { addReducer, alreadyWords, canAdd, chosenKind, kindOf, matchesOf, modeOf, readyToAdd, releaseWords, START, verdictOf, type AddAction, type AddState } from './addByName'
import { addProblems, checkName, isPackage, PACKAGE_VERSION_HELP, refOf, rowDomId, SOURCE_FIELDS, SOURCE_KINDS, SOURCE_NAMES, sourceUrl, VERSION_HELP, type SourceKind, type Watched } from './software'
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
  readonly rowIdOf?: ((kind: SourceKind, repo: string) => string | undefined) | undefined
  readonly onShowRow?: ((id: string) => void) | undefined
}

const describedBy = (id: string, error: string | undefined) => (error ? `${id}-error` : `${id}-help`)

function VersionField({ state, refs, dispatch }: Pick<FormProps, 'state' | 'refs' | 'dispatch'>) {
  const error = state.errors.version
  // A package's version is also what the check looks up known vulnerabilities in (ADR 0025).
  const help = isPackage(chosenKind(state)) ? PACKAGE_VERSION_HELP : VERSION_HELP
  return (
    <Field id="sw-version" label="Version we run" optional help={help} error={error}>
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

function NameStep({ state, busy, refs, dispatch }: FormProps) {
  const error = state.errors.name
  return (
    <>
      <h3 id="add-software-heading">Add software</h3>
      <Field id="sw-name" label="Software name" help="Type the name, such as Kubernetes. I’ll find where it’s published: GitHub, Maven Central or npm." error={error}>
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
        <Button type="submit" loading={busy}>
          Find it
        </Button>
      </div>
    </>
  )
}

function ShowRow({ kind, repo, rowIdOf, onShowRow }: { kind: SourceKind; repo: string } & Pick<FormProps, 'rowIdOf' | 'onShowRow'>) {
  const id = rowIdOf?.(kind, repo)
  if (!id) return null
  return (
    <a
      href={`#${rowDomId(id)}`}
      onClick={(event) => {
        event.preventDefault()
        onShowRow?.(id)
      }}
    >
      Show it on the list
    </a>
  )
}

function Guess({ state, dispatch, rowIdOf, onShowRow }: Pick<FormProps, 'state' | 'dispatch' | 'rowIdOf' | 'onShowRow'>) {
  const matches = matchesOf(state)
  const mode = modeOf(state)
  const answer = state.answer
  if (mode === 'single') {
    const match = matches[0]
    if (!match) return null
    const verdict = verdictOf(match)
    const kind = kindOf(match)
    return (
      <>
        <p className={styles['guess']}>
          <span className="muted">{SOURCE_NAMES[kind]} · </span>
          <b>
            <a href={sourceUrl(kind, match.repo)} target="_blank" rel="noopener noreferrer">
              {match.repo}
              <IconExternal size={12} />
              <span className="visually-hidden"> (opens {SOURCE_NAMES[kind]} in a new tab)</span>
            </a>
          </b>
          <span className="muted"> {match.what}.</span>
        </p>
        <ul className={styles['why']}>
          <li>{match.why}</li>
          {verdict.kind === 'listed' ? (
            <li role="status">
              {alreadyWords(match.repo, verdict.name)} <ShowRow kind={kind} repo={match.repo} rowIdOf={rowIdOf} onShowRow={onShowRow} />
            </li>
          ) : (
            <li role={verdict.kind === 'none' ? 'status' : undefined}>{releaseWords(match)}</li>
          )}
        </ul>
      </>
    )
  }
  if (mode === 'choose') {
    return (
      <fieldset className={styles['pick']} aria-describedby={state.errors.form ? 'sw-form-error' : undefined}>
        <legend>Which one do you mean?</legend>
        {matches.map((match, index) => {
          const verdict = verdictOf(match)
          const kind = kindOf(match)
          return (
            <div key={`${kind}:${match.repo}`} className={styles['pickRow']}>
              <input
                id={`sw-pick-${index}`}
                type="radio"
                name="sw-pick"
                value={index}
                checked={state.pick === index}
                disabled={verdict.kind !== 'add'}
                onChange={() => dispatch?.({ type: 'picked', index })}
              />
              <label htmlFor={`sw-pick-${index}`}>
                <b>{match.repo}</b>
                <span className="muted">
                  {' '}
                  On {SOURCE_NAMES[kind]}. {match.what}. {match.why} {verdict.kind === 'listed' ? alreadyWords(match.repo, verdict.name) : releaseWords(match)}
                </span>
              </label>
              {verdict.kind === 'listed' ? <ShowRow kind={kind} repo={match.repo} rowIdOf={rowIdOf} onShowRow={onShowRow} /> : null}
            </div>
          )
        })}
      </fieldset>
    )
  }
  const lead =
    state.change || answer === null
      ? 'You’re choosing where it’s published yourself.'
      : answer.status === 'found'
        ? ''
        : answer.message
  return lead ? (
    <p role={answer?.status === 'not_checked' ? 'alert' : 'status'} className={answer && answer.status !== 'found' ? styles['noMatch'] : 'muted'}>
      {lead}
    </p>
  ) : null
}

function GuessStep({ state, busy, refs, dispatch, rowIdOf, onShowRow }: FormProps) {
  const mode = modeOf(state)
  const typed = state.name.trim()
  const unmatched = mode === 'address' && !state.change && state.answer !== null
  const heading = unmatched ? `I couldn’t find “${typed}”` : `Adding ${typed}`
  const repoError = state.errors.repo
  const addable = canAdd(state)
  const addLabel = mode === 'single' ? 'Looks right, add it' : `Add ${typed}`
  return (
    <>
      <h3 id="sw-guess" tabIndex={-1}>
        {heading}
      </h3>
      <Guess state={state} dispatch={dispatch} rowIdOf={rowIdOf} onShowRow={onShowRow} />
      {mode === 'address' ? (
        <div className={styles['field']}>
          <label htmlFor="sw-kind">Published on</label>
          <select id="sw-kind" value={state.kind} onChange={(event) => dispatch?.({ type: 'kind', kind: event.target.value as SourceKind })}>
            {SOURCE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {SOURCE_NAMES[kind]}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {mode === 'address' ? (
        <Field id="sw-repo" label={SOURCE_FIELDS[state.kind].label} help={SOURCE_FIELDS[state.kind].help} error={repoError}>
          <input
            id="sw-repo"
            ref={refs?.repo}
            type="text"
            value={state.repo}
            placeholder={SOURCE_FIELDS[state.kind].placeholder}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            aria-invalid={repoError ? true : undefined}
            aria-describedby={describedBy('sw-repo', repoError)}
            onChange={(event) => dispatch?.({ type: 'typed', field: 'repo', value: event.target.value })}
          />
        </Field>
      ) : null}
      {addable ? <VersionField state={state} refs={refs} dispatch={dispatch} /> : null}
      {state.errors.form ? (
        <p className={styles['error']} id="sw-form-error" role="alert">
          {state.errors.form}
        </p>
      ) : null}
      <div className={styles['formActions']}>
        {addable ? (
          <Button type="submit" variant="primary" loading={busy}>
            {addLabel}
          </Button>
        ) : null}
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

interface AddSoftwareProps {
  readonly software: readonly Pick<WatchedSoftwareView, 'id' | 'name' | 'source'>[]
  readonly onShowRow: (id: string) => void
  readonly onAdded: (name: string) => void
}

export function AddSoftware({ software, onShowRow, onAdded }: AddSoftwareProps) {
  const names = software.map((row) => row.name)
  const watched: Watched[] = software.map((row) => ({ kind: row.source.kind, ref: row.source.ref }))
  const rowIdOf = (kind: SourceKind, repo: string) => software.find((row) => row.source.kind === kind && row.source.ref.toLowerCase() === repo.toLowerCase())?.id
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
      document.getElementById(state.step === 'guess' ? 'sw-guess' : 'sw-name')?.focus()
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
    const ready = readyToAdd(state, names, watched)
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
            const taken = `${refOf(ready.body)} is already on the list.`
            dispatch({ type: 'refused', errors: modeOf(state) === 'address' ? { repo: taken } : { form: taken } })
          } else dispatch({ type: 'refused', errors: refused ?? { form: words(error) } })
        },
        onSettled: settled,
      }),
    )
  }

  return <AddSoftwareForm state={state} busy={find.isPending || add.isPending} refs={refs} dispatch={dispatch} onSubmit={submit} rowIdOf={rowIdOf} onShowRow={onShowRow} />
}
