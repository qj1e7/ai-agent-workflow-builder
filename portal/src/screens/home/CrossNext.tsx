import { useContext } from 'react'
import type { PartView } from '../../api/types'
import { Button } from '../../ui/Button'
import { askOfCross } from './parts'
import { AskPlanner } from './primary'
import styles from './PartsList.module.css'

export function AskAboutThis({ text, ask }: { text: string; ask: (text: string) => void }) {
  return <Button onClick={() => ask(text)}>Ask about this</Button>
}

/**
 * A cross's next step, under its words: Ask about this sends the part as its own message. It draws nothing when the cross has
 * another step, such as the Software watchlist's time a watch request offers, or there is nowhere to send a question.
 */
export function CrossNext({ part }: { part: PartView }) {
  const ask = useContext(AskPlanner)
  const text = askOfCross(part)
  if (text === null || ask === null) return null
  return (
    <span className={styles['next']}>
      <AskAboutThis text={text} ask={ask} />
    </span>
  )
}
