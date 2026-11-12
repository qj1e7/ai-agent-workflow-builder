import { useEffect, useId, useRef, useState } from 'react'
import { Link } from '../../ui/Link'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useAddSoftware, useFindSoftware } from '../../api/queries'
import { Button } from '../../ui/Button'
import { IconCheck } from '../../ui/icons'
import { alreadyWords, verdictOf } from '../software/addByName'
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
