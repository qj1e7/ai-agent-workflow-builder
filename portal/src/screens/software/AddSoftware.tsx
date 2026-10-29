import { useRef, useState, type FormEvent, type RefObject } from 'react'
import { ApiError } from '../../api/client'
import { useErrorWords } from '../../api/context'
import { useAddSoftware } from '../../api/queries'
import { Button } from '../../ui/Button'
import { checkName, checkRepo, checkVersion, REPO_HELP, SOURCES_NOTE, VERSION_HELP } from './software'
import styles from './Software.module.css'

export interface FormValues {
  readonly name: string
  readonly repo: string
  readonly version: string
}

export interface FormErrors {
  readonly name?: string
  readonly repo?: string
  readonly version?: string
  readonly form?: string
}

export const EMPTY_VALUES: FormValues = { name: '', repo: '', version: '' }

interface FieldRefs {
  readonly name?: RefObject<HTMLInputElement | null>
  readonly repo?: RefObject<HTMLInputElement | null>
  readonly version?: RefObject<HTMLInputElement | null>
}

interface FieldsProps {
  readonly values: FormValues
  readonly errors: FormErrors
  readonly busy: boolean
  readonly refs?: FieldRefs
  readonly onChange?: (field: keyof FormValues, value: string) => void
  readonly onSubmit?: (event: FormEvent<HTMLFormElement>) => void
}

function Field({ id, label, optional, help, error, children }: { id: string; label: string; optional?: boolean; help: string; error: string | undefined; children: React.ReactNode }) {
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

export function AddSoftwareFields({ values, errors, busy, refs, onChange, onSubmit }: FieldsProps) {
  const describedBy = (id: string, error: string | undefined) => (error ? `${id}-error` : `${id}-help`)
  return (
    <form className={styles['addForm']} onSubmit={onSubmit} noValidate aria-labelledby="add-software-heading">
      <h2 id="add-software-heading">Add software</h2>
      <p className="muted">{SOURCES_NOTE}</p>
      <div className={styles['addGrid']}>
        <Field id="sw-name" label="Name" help="What your team calls it, such as LangGraph." error={errors.name}>
          <input
            id="sw-name"
            ref={refs?.name}
            type="text"
            value={values.name}
            maxLength={80}
            autoComplete="off"
            aria-invalid={errors.name ? true : undefined}
            aria-describedby={describedBy('sw-name', errors.name)}
            onChange={(event) => onChange?.('name', event.target.value)}
          />
        </Field>
        <Field id="sw-repo" label="GitHub repository" help={REPO_HELP} error={errors.repo}>
          <input
            id="sw-repo"
            ref={refs?.repo}
            type="text"
            value={values.repo}
            placeholder="owner/name"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            aria-invalid={errors.repo ? true : undefined}
            aria-describedby={describedBy('sw-repo', errors.repo)}
            onChange={(event) => onChange?.('repo', event.target.value)}
          />
        </Field>
        <Field id="sw-version" label="Our version" optional help={VERSION_HELP} error={errors.version}>
          <input
            id="sw-version"
            ref={refs?.version}
            type="text"
            value={values.version}
            placeholder="1.2.14"
            autoComplete="off"
            inputMode="decimal"
            spellCheck={false}
            aria-invalid={errors.version ? true : undefined}
            aria-describedby={describedBy('sw-version', errors.version)}
            onChange={(event) => onChange?.('version', event.target.value)}
          />
        </Field>
      </div>
      {errors.form ? (
        <p className={styles['error']} role="alert">
          {errors.form}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" loading={busy}>
          Add
        </Button>
      </div>
    </form>
  )
}

export function AddSoftware({ names, repos, onAdded }: { names: readonly string[]; repos: readonly string[]; onAdded: (name: string) => void }) {
  const [values, setValues] = useState<FormValues>(EMPTY_VALUES)
  const [errors, setErrors] = useState<FormErrors>({})
  const add = useAddSoftware()
  const words = useErrorWords()
  const refs = { name: useRef<HTMLInputElement>(null), repo: useRef<HTMLInputElement>(null), version: useRef<HTMLInputElement>(null) }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (add.isPending) return
    const name = checkName(values.name, names)
    const repo = checkRepo(values.repo, repos)
    const version = checkVersion(values.version)
    const found: FormErrors = {
      ...(name.ok ? {} : { name: name.words }),
      ...(repo.ok ? {} : { repo: repo.words }),
      ...(version.ok ? {} : { version: version.words }),
    }
    setErrors(found)
    if (!name.ok || !repo.ok || !version.ok) {
      const first = !name.ok ? refs.name : !repo.ok ? refs.repo : refs.version
      first.current?.focus()
      return
    }
    add.mutate(
      { name: name.value, repo: repo.value, ...(version.value === null ? {} : { our_version: version.value }) },
      {
        onSuccess: () => {
          setValues(EMPTY_VALUES)
          onAdded(name.value)
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 409) {
            setErrors({ repo: `${repo.value} is already on the list.` })
            refs.repo.current?.focus()
          } else setErrors({ form: words(error) })
        },
      },
    )
  }

  return (
    <AddSoftwareFields
      values={values}
      errors={errors}
      busy={add.isPending}
      refs={refs}
      onChange={(field, value) => setValues((current) => ({ ...current, [field]: value }))}
      onSubmit={submit}
    />
  )
}
