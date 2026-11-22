import type { ReactNode } from 'react'
import styles from './Tabs.module.css'

interface Tab<T extends string> {
  readonly id: T
  readonly label: ReactNode
}

interface TabsProps<T extends string> {
  /** What the tabs switch between, read out as the group's name, such as "Settings sections". */
  readonly label: string
  readonly tabs: readonly Tab<T>[]
  readonly current: T
  readonly onPick: (id: T) => void
}

/** The one tab bar: a row of sections on a line, the one showing underlined in ink (the sketch's .tabs). */
export function Tabs<T extends string>({ label, tabs, current, onPick }: TabsProps<T>) {
  return (
    <div className={styles['tabs']} role="group" aria-label={label}>
      {tabs.map((tab) => (
        <button key={tab.id} type="button" className={styles['tab']} aria-pressed={current === tab.id} onClick={() => onPick(tab.id)}>
          {tab.label}
        </button>
      ))}
    </div>
  )
}
