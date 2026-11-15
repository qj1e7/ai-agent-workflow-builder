import type { ReactNode } from 'react'
import type { PartView, PlannerReply } from '../../api/types'
import { useWatchlist } from '../../api/queries'
import { useOperatorsSay } from '../../shell/OperatorsNote'
import { Button } from '../../ui/Button'
import { IconCheck, IconX } from '../../ui/icons'
import { useAsker } from './asker'
import { crossLabel, crossWords, leftoverParts, MARK_WORDS, watchlistRuns, type CrossContext, type Mark } from './parts'
import styles from './PartsList.module.css'

/** One row of a parts list: her words or the part’s name, its mark, and what happened to it. */
export interface Part {
  readonly key: string
  readonly mark: Mark
  readonly label: ReactNode
  readonly body: ReactNode
}

function MarkIcon({ mark }: { mark: Mark }) {
  if (mark === 'ok') return <IconCheck size={13} strokeWidth={3} />
  if (mark === 'no') return <IconX size={12} strokeWidth={3} />
  return <>?</>
}

/** Every part of a request with its mark (spec 6.5). The mark is said in words for a screen reader, so it is never colour alone. */
export function PartsList({ parts, short = false }: { parts: readonly Part[]; short?: boolean }) {
  if (parts.length === 0) return null
  return (
    <ul className={styles['parts']} data-short={short || undefined} aria-label="Each part of your request">
      {parts.map((part) => (
        <li key={part.key} className={styles['part']} data-mark={part.mark} data-part={part.key}>
          <span className={styles['mark']} aria-hidden="true">
            <MarkIcon mark={part.mark} />
          </span>
          <span className={styles['label']}>
            <span className="visually-hidden">{MARK_WORDS[part.mark]}: </span>
            {part.label}
          </span>
          <span className={styles['body']}>{part.body}</span>
        </li>
      ))}
    </ul>
  )
}

/** The runtime’s crosses and questions as rows. `more` adds a next step to a row, such as Ask the team. */
export function crossParts(parts: readonly PartView[], context: CrossContext = {}, more?: (part: PartView) => ReactNode): Part[] {
  return parts.map((part, index) => ({
    key: `cross-${String(index)}`,
    mark: part.mark === 'question' ? 'ask' : 'no',
    label: crossLabel(part, context.when, context.short),
    body: (
      <>
        <span>{crossWords(part, context)}</span>
        {more?.(part)}
      </>
    ),
  }))
}

/**
 * The clauses an answer didn’t read, above its card. A time one software can’t have of its own is offered to the whole Software
 * watchlist, as a request she sends: the Planner answers it with the edit card, so nothing changes until she saves it.
 */
export function Leftovers({ reply, ask }: { reply: PlannerReply; ask?: (text: string) => void }) {
  const parts = leftoverParts(reply)
  const watchlist = useWatchlist({ enabled: parts.some((part) => part.reason === 'own_time') })
  const operators = useOperatorsSay()
  const operator = useAsker() === 'operator'
  if (parts.length === 0) return null
  const offer = (part: PartView) => {
    if (!ask || !operator || part.reason !== 'own_time') return null
    const words = watchlistRuns(part.text)
    return <Button onClick={() => ask(words)}>{words}</Button>
  }
  return (
    <div className={styles['leftovers']}>
      <PartsList parts={crossParts(parts, { watchlist: watchlist.data?.schedule ?? null, operators }, offer)} />
    </div>
  )
}
