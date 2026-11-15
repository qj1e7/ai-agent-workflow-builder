import { useId, useState } from 'react'
import type { UseCaseView, VersionView } from '../../api/types'
import { useErrorWords } from '../../api/context'
import { useRollback, useVersions } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { backToVersionToast } from './n8nChange'
import { versionLine } from './workflow'
import styles from './Workflows.module.css'

interface VersionsProps {
  readonly useCase: UseCaseView
  readonly now: Date
  readonly nameOf: (id: string) => string
  /** Only an Operator rolls back. */
  readonly operator: boolean
  /** Says what a roll back did, in the page's one message. */
  readonly say: (words: string) => void
}

/**
 * Versions, as the sketch draws them: a details with a row for each, "Version 3, in use" and what changed. An Operator can roll an
 * n8n workflow back to any version but the one in use, which publishes it again as a new version. A change of when it runs is
 * undone on the chat's edit card, so a workflow on the shared n8n workflow shows no Roll back.
 */
export function Versions({ useCase, now, nameOf, operator, say }: VersionsProps) {
  const versions = useVersions(useCase.use_case_id, useCase.version)
  const rollback = useRollback()
  const words = useErrorWords()
  const [problem, setProblem] = useState<string | null>(null)
  const [pressed, setPressed] = useState<number | null>(null)
  const headingId = useId()
  if (useCase.version < 2) return null
  const rollBackTo = (version: VersionView) => {
    if (rollback.isPending) return
    setPressed(version.version)
    rollback.mutate(
      { useCaseId: useCase.use_case_id, version: version.version, inUse: useCase.version, via: 'page' },
      {
        onSuccess: (view) => {
          setProblem(null)
          say(backToVersionToast(version.version, view.version))
        },
        onError: (error) => setProblem(words(error)),
      },
    )
  }
  return (
    <details className={styles['more']} aria-labelledby={headingId}>
      <summary id={headingId}>Versions</summary>
      {versions.data ? (
        <ol className={styles['rows']} aria-label="Versions, newest first">
          {versions.data.map((version) => (
            <li key={version.version} data-version={version.version} className={styles['plainRow']}>
              <span className={styles['main']}>
                <b>
                  Version {version.version}
                  {version.running ? ', in use' : ''}
                </b>
                <span className={styles['sub']}>{versionLine(version, now, nameOf)}</span>
              </span>
              {operator && !version.running && version.grade ? (
                <Button loading={rollback.isPending && pressed === version.version} onClick={() => rollBackTo(version)}>
                  Roll back<span className="visually-hidden"> to version {version.version}</span>
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
      {problem ? (
        <p className={styles['problem']} role="alert">
          {problem}
        </p>
      ) : null}
    </details>
  )
}
