import { useCallback, useEffect, useState } from 'react'
import { useSession } from '../../api/context'
import { useSettingsHistory } from '../../api/settingsQueries'
import type { SettingsArea } from '../../api/types'
import { AlertMark } from './marks'
import { historyOf, settingsErrorWords, type NotFound } from './settings'
import styles from './Settings.module.css'

export function useFocusOnNextRender(): (id: string) => void {
  const [target, setTarget] = useState<{ readonly id: string } | null>(null)
  useEffect(() => {
    if (target) document.getElementById(target.id)?.focus()
  }, [target])
  return useCallback((id: string) => setTarget({ id }), [])
}

export function useSettingsWords(): (error: unknown, missing?: NotFound, who?: string) => string {
  const { kind } = useSession()
  return (error, missing, who) => settingsErrorWords(error, kind, missing, who)
}

export function FieldError({ id, words }: { id: string; words: string | undefined }) {
  if (!words) return null
  return (
    <p className={styles['error']} id={id}>
      <AlertMark />
      <span>{words}</span>
    </p>
  )
}

export function History({ area, note }: { area: SettingsArea; note?: string }) {
  const history = useSettingsHistory()
  const words = useSettingsWords()
  const lines = history.data ? historyOf(history.data, area) : []
  return (
    <details className={styles['history']}>
      <summary>Change history{history.data ? ` (${lines.length})` : ''}</summary>
      {history.isError ? (
        <p className={styles['small']}>{words(history.error)}</p>
      ) : lines.length > 0 ? (
        <ol className={styles['timeline']}>
          {lines.map((line) => (
            <li key={line.key}>
              <b>{line.when}</b>
              <span>
                {line.summary}
                {line.who ? <span className={styles['small']}>{line.who}</span> : null}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles['small']}>{history.isPending ? 'Loading' : 'No changes yet.'}</p>
      )}
      {note ? <p className={styles['small']}>{note}</p> : null}
    </details>
  )
}
