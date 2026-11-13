import { useId } from 'react'
import type { UseCaseView } from '../../api/types'
import { useVersions } from '../../api/workflowQueries'
import { Button } from '../../ui/Button'
import { versionLine } from './workflow'
import styles from './Workflows.module.css'

interface VersionsProps {
  readonly useCase: UseCaseView
  readonly now: Date
  readonly nameOf: (id: string) => string
}

/**
 * Versions, as the sketch draws them: a details with a row for each, "Version 3, in use" and what changed. It only reads.
 * The sketch's Roll back is not here, because the platform can undo only the newest schedule change, and that is on the chat's edit card.
 */
export function Versions({ useCase, now, nameOf }: VersionsProps) {
  const versions = useVersions(useCase.use_case_id, useCase.version)
  const headingId = useId()
  if (useCase.version < 2) return null
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
    </details>
  )
}
