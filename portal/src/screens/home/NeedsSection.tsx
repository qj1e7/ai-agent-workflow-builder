import { useRef, useState, type ReactNode } from 'react'
import { NavigationType, useNavigationType } from 'react-router'
import { cx } from '../../ui/cx'
import { useGlide, usePresence } from '../../ui/presence'
import type { Need, Needs } from './home'
import { NeedItem } from './HomeItem'
import styles from './Home.module.css'

export interface Arrival {
  readonly page: boolean
  readonly arrive: (key: string) => boolean
  readonly stagger: (key: string) => number
}

export function useArrival(firstKeys: readonly string[]): Arrival {
  const firstLoadOrBack = useNavigationType() === NavigationType.Pop
  const [first] = useState(() => new Map(firstKeys.map((key, index) => [key, index])))
  return {
    page: !firstLoadOrBack,
    arrive: (key) => !firstLoadOrBack || !first.has(key),
    stagger: (key) => first.get(key) ?? 0,
  }
}

function Count({ value }: { value: number }) {
  const [first] = useState(value)
  const changed = value !== first
  return (
    <span key={changed ? value : 'first'} className={cx(styles['count'], changed && styles['bump'])}>
      {value}
    </span>
  )
}

function NeedsList({ needs, now, arrival }: { needs: readonly Need[]; now: Date; arrival: Arrival }) {
  const list = useRef<HTMLUListElement>(null)
  const shown = usePresence(needs, (need) => need.key)
  useGlide(list)
  return (
    <ul ref={list} className={styles['needs']} aria-label="Needs you">
      {shown.map(({ key, item, leaving, onAnimationEnd }, index) => (
        <NeedItem
          key={key}
          need={item}
          card={index === 0}
          now={now}
          motion={{ glide: key, arrive: arrival.arrive(key), stagger: arrival.stagger(key) + 1, leaving, onAnimationEnd }}
        />
      ))}
    </ul>
  )
}

interface NeedsSectionProps {
  readonly needs: Needs
  readonly now: Date
  readonly arrival: Arrival
  readonly more: ReactNode
  readonly whenNone: ReactNode
}

/** Needs you, drawn the same on Home and on Workflows. `whenNone` is what shows with nothing in it, or null to show nothing. */
export function NeedsSection({ needs, now, arrival, more, whenNone }: NeedsSectionProps) {
  if (needs.shown.length === 0 && whenNone === null) return null
  return (
    <section className={cx(styles['section'], arrival.page && styles['arrive'])} aria-labelledby="needs-h">
      <h2 id="needs-h">
        Needs you <Count value={needs.total} />
      </h2>
      {needs.shown.length > 0 ? <NeedsList needs={needs.shown} now={now} arrival={arrival} /> : whenNone}
      {more}
    </section>
  )
}
