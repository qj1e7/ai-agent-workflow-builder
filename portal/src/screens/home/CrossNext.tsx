import { useContext, useState, type ReactNode, type Ref } from 'react'
import type { PartView, ScheduleView } from '../../api/types'
import { useWatchlist } from '../../api/queries'
import { Button } from '../../ui/Button'
import { CHANGED_SINCE_OPENED } from '../workflows/workflow'
import { ScheduleEditor, useEditorThatRefocusesItsOpener } from '../software/Schedule'
import { useAsker } from './asker'
import { nextStepOf } from './parts'
import { AskPlanner } from './primary'
import styles from './PartsList.module.css'

export function AskAboutThis({ text, ask }: { text: string; ask: (text: string) => void }) {
  return <Button onClick={() => ask(text)}>Ask about this</Button>
}

interface ChangeWhenProps {
  readonly editing: boolean
  readonly onOpen: () => void
  readonly opener: Ref<HTMLButtonElement>
  readonly editor: ReactNode
  readonly problem: string | null
}

/** The button that opens the Software watchlist’s own schedule form under a cross, and the form once it is open. */
export function ChangeWhen({ editing, onOpen, opener, editor, problem }: ChangeWhenProps) {
  return (
    <>
      {editing ? null : (
        <Button ref={opener} onClick={onOpen}>
          Change when the watchlist checks
        </Button>
      )}
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      {editing ? editor : null}
    </>
  )
}

function WatchlistTime({ schedule, version }: { schedule: ScheduleView | null; version: number }) {
  const { editing, opener, open, close } = useEditorThatRefocusesItsOpener()
  const [problem, setProblem] = useState<string | null>(null)
  const stale = () => {
    setProblem(CHANGED_SINCE_OPENED)
    close()
  }
  return (
    <ChangeWhen
      editing={editing}
      opener={opener}
      onOpen={() => {
        setProblem(null)
        open()
      }}
      problem={problem}
      editor={<ScheduleEditor schedule={schedule} version={version} onDone={close} onStale={stale} />}
    />
  )
}

function WatchlistTimeStep() {
  const watchlist = useWatchlist()
  return watchlist.data ? <WatchlistTime schedule={watchlist.data.schedule} version={watchlist.data.version} /> : null
}

/** The next step of one cross, under its words. It draws nothing when there is none, or nowhere to send a question. */
export function CrossNext({ part }: { part: PartView }) {
  const asker = useAsker()
  const ask = useContext(AskPlanner)
  const step = nextStepOf(part, asker)
  if (step === null) return null
  return (
    <span className={styles['next']}>
      {step.kind === 'ask' ? ask ? <AskAboutThis text={step.text} ask={ask} /> : null : <WatchlistTimeStep />}
    </span>
  )
}
