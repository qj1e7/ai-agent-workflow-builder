import { personTone } from './personTone'
import styles from './PersonInitial.module.css'

/** A person's initial on their own colours. The name is said beside it, so it is hidden from screen readers. */
export function PersonInitial({ name, size = 34 }: { name: string; size?: number }) {
  const tone = personTone(name)
  return (
    <span
      className={styles['initial']}
      style={{ background: tone.bg, color: tone.ink, width: size, height: size, fontSize: size * 0.4 }}
      aria-hidden="true"
    >
      {name.charAt(0)}
    </span>
  )
}
