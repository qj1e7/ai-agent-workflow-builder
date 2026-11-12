import { useId, useRef, useState } from 'react'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import type { UseCaseView } from '../../api/types'
import { useRereadWorkflow, useUndoVersion, useVersions } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { mayUndo, meansOutOfDate, pressChange, undoneWords, undoProblem, versionLine, type Viewer } from './workflow'
import styles from './Workflows.module.css'

interface VersionsProps {
  readonly useCase: UseCaseView
  readonly viewer: Viewer
  readonly now: Date
  readonly nameOf: (id: string) => string
  readonly say: (words: string) => void
}

/** The prototype's Versions panel, shown once a change has published a second version. Undo on the newest publishes the schedule from before it again. */
export function Versions({ useCase, viewer, now, nameOf, say }: VersionsProps) {
  const id = useCase.use_case_id
  const versions = useVersions(id, useCase.version)
  const undo = useUndoVersion(id)
  const reread = useRereadWorkflow()
  const words = useErrorWords()
  const latch = useLatch()
  const heading = useRef<HTMLHeadingElement>(null)
  const headingId = useId()
  const [problem, setProblem] = useState<string | null>(null)
  if (useCase.version < 2) return null

  function press(version: number) {
    pressChange(latch, (outcome) => undo.mutate(version, outcome), {
      onSuccess: (view: UseCaseView) => {
        setProblem(null)
        say(undoneWords(view))
        heading.current?.focus()
      },
      onError: (error) => {
        setProblem(undoProblem(version, useCase.name, error, words))
        if (meansOutOfDate(error)) reread(id)
      },
    })
  }

  return (
    <section className={styles['panel']} aria-labelledby={headingId}>
      <h2 id={headingId} ref={heading} tabIndex={-1}>
        Versions
      </h2>
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
      {versions.data ? (
        <ol className={styles['versions']} aria-label="Versions, newest first">
          {versions.data.map((version) => (
            <li key={version.version} data-version={version.version}>
              <span>
                <b>Version {version.version}</b>
                <span>{versionLine(version, now, nameOf)}</span>
              </span>
              {mayUndo(version, viewer) && !versions.isPlaceholderData ? (
                <Button loading={undo.isPending} onClick={() => press(version.version)}>
                  Undo<span className="visually-hidden"> version {version.version}</span>
                </Button>
              ) : null}
            </li>
          ))}
        </ol>
      ) : versions.isError ? (
        <p>
          The versions could not be loaded. <Button onClick={() => void versions.refetch()}>Try again</Button>
        </p>
      ) : (
        <p className="muted" role="status">
          Loading the versions
        </p>
      )}
    </section>
  )
}
