import type { ToolView } from '../../api/types'
import { toolName } from './cardDraft'
import styles from './Form.module.css'

export function ToolChips({ ids, tools }: { ids: readonly string[]; tools: readonly ToolView[] | undefined }) {
  if (ids.length === 0) return null
  return (
    <ul className={styles['chips']} aria-label="Tools it uses">
      {ids.map((id) => (
        <li key={id}>{toolName(tools, id)}</li>
      ))}
    </ul>
  )
}
