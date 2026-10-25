import type { ReactNode } from 'react'
import { InlineMessage } from '../../ui/Feedback'
import { IconAlert } from '../../ui/icons'
import styles from './Form.module.css'

interface FieldProps {
  id: string
  label: ReactNode
  help?: string | null
  problem?: string | null
  /** A problem that changes as the Operator types is not announced. A problem after Save is. */
  quiet?: boolean
  children: ReactNode
}

/** The id of the element that holds a field's help and its problem, for aria-describedby. */
export function describedBy(id: string, help: boolean, problem: boolean): string | undefined {
  return [help ? `${id}-help` : null, problem ? `${id}-problem` : null].filter(Boolean).join(' ') || undefined
}

export function Field({ id, label, help = null, problem = null, quiet = false, children }: FieldProps) {
  return (
    <div className={styles['field']}>
      <label htmlFor={id}>{label}</label>
      {children}
      {help ? (
        <p id={`${id}-help`} className={styles['help']}>
          {help}
        </p>
      ) : null}
      {problem ? (
        quiet ? (
          <p id={`${id}-problem`} className={styles['problem']}>
            <IconAlert size={16} />
            <span>{problem}</span>
          </p>
        ) : (
          <InlineMessage tone="error" id={`${id}-problem`}>
            {problem}
          </InlineMessage>
        )
      ) : null}
    </div>
  )
}
