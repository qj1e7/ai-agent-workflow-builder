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

/** The prototype's Versions panel, shown once a change has published a second version. It only reads: Undo is on the chat's edit card. */
export function Versions({ useCase, now, nameOf }: VersionsProps) {
  const versions = useVersions(useCase.use_case_id, useCase.version)
  const headingId = useId()
  if (useCase.version < 2) return null
  return (
    <section className={styles['panel']} aria-labelledby={headingId}>
      <h2 id={headingId}>Versions</h2>
      {versions.data ? (
        <ol className={styles['versions']} aria-label="Versions, newest first">
          {versions.data.map((version) => (
            <li key={version.version} data-version={version.version}>
              <b>Version {version.version}</b>
              <span>{versionLine(version, now, nameOf)}</span>
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
