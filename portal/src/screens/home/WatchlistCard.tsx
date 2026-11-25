import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from '../../ui/Link'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddSoftware, useFindSoftware, useSaveSchedule, useWatchlist } from '../../api/queries'
import type { FindOut, ScheduleView } from '../../api/types'
import { stillChecksWords, watchlistRunsWords, watchSavedWords } from './answers'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { IconCheck } from '../../ui/icons'
import { alreadyWords, chooseWords, clearMatch, kindOf, verdictOf } from '../software/addByName'
import { describedBy, Field } from '../software/Field'
import { addedVulnerabilityWords, checkName, homeAdd, isPackage, HOME_PACKAGE_VERSION_HELP, NAME_HELP, refOf, SOURCE_NAMES } from '../software/software'
import { useMainButton } from './primary'
import styles from './Planner.module.css'

const WATCHLIST = '/software'

/**
 * Adds one piece of software to the Software watchlist from Home. It finds where it is published first, a GitHub project or
 * a Maven Central or npm package, and shows it, so the person sees where the versions come from before anything is saved.
 * Several matches, or none, are chosen on the watchlist.
 */
export function AddToWatchlist({ name, then = null }: { name: string; then?: { readonly day: ScheduleView['day']; readonly at: string } | null }) {
  const find = useFindSoftware()
  const add = useAddSoftware()
  const move = useSaveSchedule()
  const watchlist = useWatchlist({ enabled: then !== null })
  const latch = useLatch()
  const words = useErrorWords()
  const main = useMainButton()
  const asked = useRef<string | null>(null)
  const versionId = useId()
  const versionBox = useRef<HTMLInputElement>(null)
  const [kept, setKept] = useState(false)
  // A package's version, the only one its known vulnerabilities are looked up in (ADR 0025).
  const [version, setVersion] = useState('')
  const [versionError, setVersionError] = useState<string | undefined>(undefined)
  const { mutate } = find
  useEffect(() => {
    if (asked.current === name) return
    asked.current = name
    mutate(name)
  }, [name, mutate])

  // With the watch card's move, an Add that can't finish says the watchlist keeps its own schedule.
  const still = then && watchlist.data ? stillChecksWords(watchlist.data) : null
  const unmoved = (line: ReactNode) => (
    <>
      {line}
      {still ? <p>{still}</p> : null}
    </>
  )
  if (kept) return <p className="muted">Not added. Nothing changed.</p>
  if (add.isSuccess) {
    const added = add.variables
    const where = SOURCE_NAMES[added.package?.kind ?? 'github']
    const moved = move.data?.schedule
    return (
      <>
        <p className={styles['sent']} role="status">
          <IconCheck size={18} />
          <span>
            <b>{name} is on the Software watchlist.</b> Its versions are read from {where}, from {refOf(added)}.
            {added.package ? ` ${addedVulnerabilityWords(added)}` : ''}{' '}
            <Link to={WATCHLIST}>Open the Software watchlist</Link>
          </span>
        </p>
        {move.isSuccess && moved ? <p role="status">{watchSavedWords(move.data.version, move.data.software.length, watchlistRunsWords(moved))}</p> : null}
        {move.isError ? <p role="alert">{words(move.error)}</p> : null}
      </>
    )
  }
  if (find.isPending || find.isIdle) {
    return (
      <p className="muted" role="status">
        Looking up where {name} is published.
      </p>
    )
  }
  const answer = find.data
  if (find.isError || answer === undefined) {
    return unmoved(
      <p role="alert">
        I couldn’t look that up just now. {find.isError ? words(find.error) : ''} <Link to={WATCHLIST}>Add it on the Software watchlist</Link>
      </p>,
    )
  }
  if (answer.status !== 'found') return unmoved(<NothingFound name={name} answer={answer} />)
  // Only a single match from our reviewed list is offered here. A match found by searching GitHub is always the person's choice.
  const only = clearMatch(answer.matches)
  if (only === undefined) {
    return unmoved(
      <p>
        {chooseWords(name, answer.matches)} <Link to={WATCHLIST}>Choose on the Software watchlist</Link>.
      </p>,
    )
  }
  const verdict = verdictOf(only)
  if (verdict.kind === 'listed') {
    return unmoved(
      <p>
        {alreadyWords(only.repo, verdict.name)} <Link to={WATCHLIST}>Open the Software watchlist</Link>
      </p>,
    )
  }
  if (verdict.kind === 'none') {
    return unmoved(
      <p>
        {only.repo} has no releases the check can count, so there is nothing to compare. <Link to={WATCHLIST}>Open the Software watchlist</Link>
      </p>,
    )
  }
  const kind = kindOf(only)
  const pkg = isPackage(kind)
  // With the watch card's move, the whole watchlist moves to the time asked once it holds the software, from the version Add made.
  // The promise carries the move on even when the card leaves the screen before Add answers.
  const moveTo = (saved: number) => (then ? move.mutate({ ...then, expected_version: saved }) : undefined)
  const press = () => {
    const body = homeAdd(name, kind, only.repo, version)
    if (!body.ok) {
      setVersionError(body.words)
      versionBox.current?.focus()
      return
    }
    latch.run((settled) => {
      void add
        .mutateAsync(body.value)
        .then((view) => moveTo(view.version), () => undefined)
        .finally(settled)
    })
  }
  return (
    <>
      <p>
        <b>{only.repo}</b> on {SOURCE_NAMES[kind]}. {only.what} {only.why}
      </p>
      {pkg ? (
        <Field id={versionId} label="Version we run" optional help={HOME_PACKAGE_VERSION_HELP} error={versionError}>
          <input
            id={versionId}
            ref={versionBox}
            type="text"
            value={version}
            placeholder="1.2.14"
            autoComplete="off"
            inputMode="decimal"
            spellCheck={false}
            aria-invalid={versionError ? true : undefined}
            aria-describedby={describedBy(versionId, versionError)}
            onChange={(event) => {
              setVersion(event.target.value)
              setVersionError(undefined)
            }}
          />
        </Field>
      ) : null}
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
      {add.isError && still ? <p>{still}</p> : null}
    </>
  )
}

/**
 * The finder offered nothing. When GitHub could not be asked, as when its search is busy, the answer says what went wrong, as the
 * Software page does, and never that nothing was found. Either way the person can add it on the Software watchlist by hand.
 */
export function NothingFound({ name, answer }: { name: string; answer: Exclude<FindOut, { status: 'found' }> }) {
  if (answer.status === 'not_checked') {
    return (
      <p role="alert">
        {answer.message} <Link to={WATCHLIST}>Add it on the Software watchlist</Link>
      </p>
    )
  }
  return (
    <p>
      I couldn’t find where {name} is published. <Link to={WATCHLIST}>Add it on the Software watchlist</Link> and choose GitHub, Maven Central or npm.
    </p>
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
