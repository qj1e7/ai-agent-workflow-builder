import type { ReactNode } from 'react'
import styles from './Software.module.css'

/** A form field as the Software page draws it: the label above the box, and under it the help, or the problem in its place. */
export function Field({ id, label, optional, help, error, children }: { id: string; label: string; optional?: boolean; help: string; error: string | undefined; children: ReactNode }) {
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

/** The line a field's box points to: the problem when there is one, else the help. */
export const describedBy = (id: string, error: string | undefined): string => (error ? `${id}-error` : `${id}-help`)
