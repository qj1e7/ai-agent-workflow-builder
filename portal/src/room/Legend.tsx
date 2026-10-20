import { IconCheck, IconClock, IconX } from '../ui/icons'
import styles from './Legend.module.css'

export function Legend() {
  return (
    <ul className={styles['legend']} aria-label="How to read the room">
      <li>
        <span className={styles['square']} aria-hidden="true" />
        Agent
      </li>
      <li>
        <span className={styles['circle']} aria-hidden="true" />
        Person
      </li>
      <li>
        <span className={styles['ring']} aria-hidden="true" />
        Working
      </li>
      <li className={styles['wait']}>
        <IconClock size={14} />
        Waiting for a person
      </li>
      <li className={styles['fail']}>
        <IconX size={14} />
        Failed here
      </li>
      <li className={styles['done']}>
        <IconCheck size={14} />
        Done
      </li>
      <li>
        <span className={styles['path']} aria-hidden="true" />
        Path travelled
      </li>
    </ul>
  )
}
