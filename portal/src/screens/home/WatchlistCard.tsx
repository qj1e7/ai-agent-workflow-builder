import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link } from '../../ui/Link'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddSoftware, useFindSoftware } from '../../api/queries'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { IconCheck } from '../../ui/icons'
import { alreadyWords, verdictOf } from '../software/addByName'
import { describedBy, Field } from '../software/Field'
import { checkName, NAME_HELP } from '../software/software'
import { useMainButton } from './primary'
import styles from './Planner.module.css'

const WATCHLIST = '/software'

/**
 * Adds one piece of software to the Software watchlist from Home. It finds the GitHub project first and shows it, so the
 * person sees where the releases come from before anything is saved. Several matches, or none, are chosen on the watchlist.
 */
export function AddToWatchlist({ name }: { name: string }) {
  const find = useFindSoftware()
  const add = useAddSoftware()
  const latch = useLatch()
  const words = useErrorWords()
  const main = useMainButton()
  const asked = useRef<string | null>(null)
  const [kept, setKept] = useState(false)
  const { mutate } = find
  useEffect(() => {
    if (asked.current === name) return
    asked.current = name
    mutate(name)
  }, [name, mutate])

  if (kept) return <p className="muted">Not added. Nothing changed.</p>
  if (add.isSuccess) {
    const added = add.variables
    return (
      <p className={styles['sent']} role="status">
        <IconCheck size={18} />
        <span>
          <b>{name} is on the Software watchlist.</b> Its releases are read from GitHub, from {added.repo}.{' '}
          <Link to={WATCHLIST}>Open the Software watchlist</Link>
        </span>
      </p>
    )
  }
  if (find.isPending || find.isIdle) {
    return (
      <p className="muted" role="status">
        Looking for {name}’s GitHub project.
      </p>
    )
  }
  const answer = find.data
  if (find.isError || answer === undefined) {
    return (
      <p role="alert">
        I couldn’t look that up just now. {find.isError ? words(find.error) : ''} <Link to={WATCHLIST}>Add it on the Software watchlist</Link>
      </p>
    )
  }
  if (answer.status !== 'found') {
    return (
      <p>
        I couldn’t find {name}’s GitHub project. <Link to={WATCHLIST}>Add it on the Software watchlist</Link> with its address.
      </p>
    )
  }
  const [only, ...others] = answer.matches
  if (only === undefined || others.length > 0) {
    return (
      <p>
        More than one project could be {name}. <Link to={WATCHLIST}>Choose on the Software watchlist</Link>.
      </p>
    )
  }
  const verdict = verdictOf(only)
  if (verdict.kind === 'listed') {
    return (
      <p>
        {alreadyWords(only.repo, verdict.name)} <Link to={WATCHLIST}>Open the Software watchlist</Link>
      </p>
    )
  }
  if (verdict.kind === 'none') {
    return (
      <p>
        {only.repo} has no releases the check can count, so there is nothing to compare. <Link to={WATCHLIST}>Open the Software watchlist</Link>
      </p>
    )
  }
  const press = () => latch.run((settled) => add.mutate({ name, repo: only.repo }, { onSettled: settled }))
  return (
    <>
      <p>
        <b>{only.repo}</b> on GitHub. {only.what} {only.why}
      </p>
      <div className={styles['buttons']}>
        <Button variant={main} loading={add.isPending} onClick={press}>
          Add {name}
        </Button>
        <Button onClick={() => setKept(true)}>Never mind</Button>
      </div>
      {add.isError ? (
        <p className={styles['problem']} role="alert">
          Could not add it. {words(add.error)}
        </p>
      ) : null}
    </>
  )
}

/**
 * Which software: the Planner heard a watch word with no name. It asks for the name as Add software does on the Software page, in a
 * card like the chat's other answers, with no title: the Planner's question above it already says what it is for. Find it is never
 * dead: with no name, the field says why and keeps focus.
 */
export function WhichSoftware({ onNever }: { onNever: () => void }) {
  const fieldId = useId()
  const titleId = useId()
  const main = useMainButton()
  const field = useRef<HTMLInputElement>(null)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | undefined>(undefined)
  const [name, setName] = useState<string | null>(null)
  // The form goes once they name it, so focus moves to the card for that name rather than dropping to the page.
  useEffect(() => {
    if (name !== null) document.getElementById(titleId)?.focus()
  }, [name, titleId])
  if (name !== null) {
    return (
      <Card title={name} headingId={titleId}>
        <AddToWatchlist name={name} />
      </Card>
    )
  }
  const find = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const checked = checkName(typed)
    if (checked.ok) {
      setName(checked.value)
      return
    }
    setError(checked.words)
    field.current?.focus()
  }
  return (
    <form onSubmit={find} noValidate>
      <Card
        label="Software to watch"
        actions={
          <>
            <Button variant={main} type="submit">
              Find it
            </Button>
            <Button onClick={onNever}>Never mind</Button>
          </>
        }
      >
        <Field id={fieldId} label="Software name" help={NAME_HELP} error={error}>
          <input
            ref={field}
            id={fieldId}
            type="text"
            value={typed}
            maxLength={80}
            autoComplete="off"
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy(fieldId, error)}
            onChange={(event) => {
              setTyped(event.target.value)
              setError(undefined)
            }}
          />
        </Field>
      </Card>
    </form>
  )
}
