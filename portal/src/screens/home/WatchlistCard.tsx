import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddSoftware, useFindSoftware } from '../../api/queries'
import { Button } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { alreadyWords, kindOf, verdictOf } from '../software/addByName'
import { addBody, isPackage, refOf, SOURCE_NAMES } from '../software/software'
import { useMainButton } from './primary'
import styles from './Planner.module.css'

const WATCHLIST = '/software'

/**
 * Adds one piece of software to the Software watchlist from Home. It finds where it is published first, a GitHub project or
 * a Maven Central or npm package, and shows it, so the person sees where the versions come from before anything is saved.
 * Several matches, or none, are chosen on the watchlist.
 */
export function AddToWatchlist({ name }: { name: string }) {
  const find = useFindSoftware()
  const add = useAddSoftware()
  const latch = useLatch()
  const words = useErrorWords()
  const main = useMainButton()
  const asked = useRef<string | null>(null)
  const { mutate } = find
  useEffect(() => {
    if (asked.current === name) return
    asked.current = name
    mutate(name)
  }, [name, mutate])

  if (add.isSuccess) {
    const added = add.variables
    const where = SOURCE_NAMES[added.package?.kind ?? 'github']
    return (
      <p className={styles['sent']} role="status">
        <IconCheck size={18} />
        <span>
          <b>{name} is on the Software watchlist.</b> Its versions are read from {where}, from {refOf(added)}.{' '}
          <Link to={WATCHLIST}>Open the Software watchlist</Link>
        </span>
      </p>
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
    return (
      <p role="alert">
        I couldn’t look that up just now. {find.isError ? words(find.error) : ''} <Link to={WATCHLIST}>Add it on the Software watchlist</Link>
      </p>
    )
  }
  if (answer.status !== 'found') {
    return (
      <p>
        I couldn’t find where {name} is published. <Link to={WATCHLIST}>Add it on the Software watchlist</Link> and choose GitHub, Maven Central or npm.
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
  const kind = kindOf(only)
  const press = () => latch.run((settled) => add.mutate(addBody(name, kind, only.repo, null), { onSettled: settled }))
  return (
    <>
      <p>
        <b>{only.repo}</b> on {SOURCE_NAMES[kind]}. {only.what} {only.why}
        {isPackage(kind) ? ' Each check also looks up known vulnerabilities in the version you run, once you give it on the Software watchlist.' : ''}
      </p>
      <div className={styles['buttons']}>
        <Button variant={main} loading={add.isPending} onClick={press}>
          Add {name}
        </Button>
      </div>
      {add.isError ? (
        <p className={styles['problem']} role="alert">
          Could not add it. {words(add.error)}
        </p>
      ) : null}
    </>
  )
}

/** Which software: the Planner heard a release word with no name. */
export function WhichSoftware({ onNever }: { onNever: () => void }) {
  const fieldId = useId()
  const main = useMainButton()
  const [typed, setTyped] = useState('')
  const [name, setName] = useState<string | null>(null)
  if (name !== null) return <AddToWatchlist name={name} />
  return (
    <form
      className={styles['ask']}
      onSubmit={(event) => {
        event.preventDefault()
        if (typed.trim() !== '') setName(typed.trim())
      }}
    >
      <label htmlFor={fieldId}>Software name</label>
      <input id={fieldId} type="text" value={typed} maxLength={80} autoComplete="off" placeholder="Kubernetes" onChange={(event) => setTyped(event.target.value)} />
      <div className={styles['buttons']}>
        <Button variant={main} type="submit" disabled={typed.trim() === ''}>
          Find it
        </Button>
        <Button onClick={onNever}>Never mind</Button>
      </div>
    </form>
  )
}
