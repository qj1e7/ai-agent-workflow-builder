import { pillLook, type PillTone } from './Pill'
import styles from './StateMark.module.css'

interface StateMarkProps {
  readonly tone: PillTone | undefined
  /** The state's words, the same as its pill says. The mark holds no text, so it is named and titled with them. */
  readonly label: string
}

/**
 * The sketch's state mark (`.dstate`): the pill's picture without its word, for a place with room for a name and no more, such as the slim
 * list. It takes the pill's own look, so a state looks the same wherever it is drawn. It is one picture with one name.
 */
export function StateMark({ tone, label }: StateMarkProps) {
  return <span className={styles['mark']} data-look={pillLook(tone)} role="img" aria-label={label} title={label} />
}
