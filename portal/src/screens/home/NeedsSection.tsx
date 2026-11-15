import { useId, useRef, useState, type ReactNode } from 'react'
import { NavigationType, useNavigationType } from 'react-router'
import { cx } from '../../ui/cx'
import { useGlide, usePresence } from '../../ui/presence'
import { groupOf, NEED_GROUPS, type Need, type Needs } from './home'
import { NeedItem, NeedRow } from './HomeItem'
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

type Drawn = ReturnType<typeof usePresence<Need>>[number]

interface GroupProps {
  readonly label: string
  readonly items: readonly { readonly drawn: Drawn; readonly first: boolean }[]
  readonly now: Date
  readonly arrival: Arrival
  readonly quiet: boolean
  readonly connectAbove: boolean
}

/** One group of Needs you. Each group glides its own rows when one leaves, so a row never crosses a heading. */
function NeedsGroup({ label, items, now, arrival, quiet, connectAbove }: GroupProps) {
  const list = useRef<HTMLUListElement>(null)
  const headingId = useId()
  useGlide(list)
  return (
    <li className={styles['group']}>
      <h3 id={headingId}>{label}</h3>
      <ul ref={list} className={styles['needs']} aria-labelledby={headingId}>
        {items.map(({ drawn: { key, item, leaving, onAnimationEnd }, first }) => (
          <NeedItem
            key={key}
            need={item}
            card={first}
            quiet={quiet}
            connectAbove={connectAbove}
            now={now}
            motion={{ glide: key, arrive: arrival.arrive(key), stagger: arrival.stagger(key) + 1, leaving, onAnimationEnd }}
          />
        ))}
      </ul>
    </li>
  )
}

function NeedsList({ needs, now, arrival, quiet, connectAbove }: { needs: readonly Need[]; now: Date; arrival: Arrival; quiet: boolean; connectAbove: boolean }) {
  const shown = usePresence(needs, (need) => need.key)
  return (
    <ul className={styles['groups']} aria-label="Needs you">
      {NEED_GROUPS.map(([group, label]) => {
        const items = shown.flatMap((drawn, index) => (groupOf(drawn.item) === group ? [{ drawn, first: index === 0 }] : []))
        return items.length > 0 ? <NeedsGroup key={group} label={label} items={items} now={now} arrival={arrival} quiet={quiet} connectAbove={connectAbove} /> : null
      })}
    </ul>
  )
}

interface NeedsSectionProps {
  readonly needs: Needs
  readonly now: Date
  readonly arrival: Arrival
  readonly more: ReactNode
  readonly whenNone: ReactNode
  /** No main button: another answer on the page has it. */
  readonly quiet?: boolean
  /** The id a link to this section points at. */
  readonly anchor?: string
  /** The page has Connect a model above the list, so the model's row points to it instead of offering a second one. */
  readonly connectAbove?: boolean
}

/** Needs you, drawn the same on Home and on Workflows. `whenNone` is what shows with nothing in it, or null to show nothing. */
export function NeedsSection({ needs, now, arrival, more, whenNone, quiet = false, anchor, connectAbove = false }: NeedsSectionProps) {
  const headingId = useId()
  if (needs.shown.length === 0 && whenNone === null) return null
  return (
    <section id={anchor} className={cx(styles['section'], arrival.page && styles['arrive'])} aria-labelledby={headingId}>
      <h2 id={headingId}>
        Needs you <Count value={needs.total} />
      </h2>
      {needs.shown.length > 0 ? <NeedsList needs={needs.shown} now={now} arrival={arrival} quiet={quiet} connectAbove={connectAbove} /> : whenNone}
      {more}
    </section>
  )
}

/** A group label is a level 2 heading on Home, which has no Needs you heading, and level 3 under Workflows' Needs you. */
type Level = 2 | 3

function RowGroup({ label, needs, now, level }: { label: string; needs: readonly Need[]; now: Date; level: Level }) {
  const headingId = useId()
  const Heading = level === 2 ? 'h2' : 'h3'
  return (
    <li className={styles['group']}>
      <Heading id={headingId}>{label}</Heading>
      <ul className={styles['needRows']} aria-labelledby={headingId}>
        {needs.map((need) => (
          <NeedRow key={need.key} need={need} now={now} />
        ))}
      </ul>
    </li>
  )
}

/**
 * Needs you as plain rows under Do now and Set up, with no count or buttons, as the sketch draws it on Home and on Workflows, so both
 * say every row in the same words and tone. `more` follows the rows.
 */
export function NeedRows({ needs, now, more, level = 2 }: { needs: readonly Need[]; now: Date; more: ReactNode; level?: Level }) {
  if (needs.length === 0) return null
  return (
    <div className={styles['plain']}>
      <ul className={styles['groups']} aria-label="Needs you">
        {NEED_GROUPS.map(([group, label]) => {
          const rows = needs.filter((need) => groupOf(need) === group)
          return rows.length > 0 ? <RowGroup key={group} label={label} needs={rows} now={now} level={level} /> : null
        })}
      </ul>
      {more}
    </div>
  )
}
