import { useMemo, useRef, useState } from 'react'
import { Link, NavigationType, useNavigationType } from 'react-router'
import { useHome } from '../../api/homeQueries'
import { isOperator } from '../../api/me'
import { useMe } from '../../api/queries'
import type { HomeOut, WaitingItem } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { useFocusWhenReady } from '../../ui/focus'
import { IconClock } from '../../ui/icons'
import { useGlide, usePresence } from '../../ui/presence'
import { comingUpOf, HOW_IT_WORKS, leadLine, moreWords, needsOf, needsTotal, type Need, type Next } from './home'
import { FirstWorkflow } from './FirstWorkflow'
import { DraftRow, NeedItem, WaitingRow } from './HomeItem'
import styles from './Home.module.css'

const HOW_ID = 'how-it-works'

interface HomePageProps {
  readonly heading: string
  readonly today: string
  readonly now: Date
}

export function HomePage({ heading, today, now }: HomePageProps) {
  const home = useHome()
  const loaded = home.data
  const total = loaded ? needsTotal(loaded) : 0
  const next = loaded ? comingUpOf(loaded, now) : null
  return (
    <div className={styles['home']}>
      <PageHead heading={heading} lead={loaded ? `${today} ${leadLine(total, loaded.workflows)}` : today}>
        {total > 0 && next ? <ComingNext next={next} /> : null}
      </PageHead>
      {loaded && home.isError ? (
        <p className="muted" role="status">
          Could not refresh. Trying again in a moment.
        </p>
      ) : null}
      {loaded ? (
        <Loaded now={now} home={loaded} next={next} />
      ) : home.isError ? (
        <>
          <p role="alert">Home could not be loaded.</p>
          <Button onClick={() => void home.refetch()}>Try again</Button>
        </>
      ) : (
        <p className="muted" role="status">
          Loading what needs you
        </p>
      )}
    </div>
  )
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

function ComingNext({ next }: { next: Next }) {
  return (
    <div className={styles['coming']}>
      <IconClock size={16} />
      <span>
        <b>Coming up next:</b> <Link to={next.to}>{next.name}</Link>, {next.when}
        {next.more > 0 ? `, and ${next.more} more` : ''}.
      </span>
      <Link to="/workflows">See all workflows</Link>
    </div>
  )
}

function AllQuiet({ next }: { next: Next | null }) {
  return (
    <div className={styles['quiet']}>
      <b>All quiet</b>
      {next ? (
        <>
          Next up: <Link to={next.to}>{next.name}</Link>, {next.when}.
        </>
      ) : (
        'Nothing is scheduled yet.'
      )}
    </div>
  )
}

interface Arrival {
  readonly page: boolean
  readonly arrive: (key: string) => boolean
  readonly stagger: (key: string) => number
}

function useArrival(firstKeys: readonly string[]): Arrival {
  const firstLoadOrBack = useNavigationType() === NavigationType.Pop
  const [first] = useState(() => new Map(firstKeys.map((key, index) => [key, index])))
  return {
    page: !firstLoadOrBack,
    arrive: (key) => !firstLoadOrBack || !first.has(key),
    stagger: (key) => first.get(key) ?? 0,
  }
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

function WaitingList({ items, total, now, arrival }: { items: readonly WaitingItem[]; total: number; now: Date; arrival: Arrival }) {
  const list = useRef<HTMLUListElement>(null)
  const shown = usePresence(items, (item) => `waiting:${item.run_id}`)
  useGlide(list)
  return (
    <section className={styles['section']} aria-labelledby="waiting-h">
      <h2 id="waiting-h">Waiting on others</h2>
      <ul ref={list} className={styles['rows']}>
        {shown.map(({ key, item, leaving, onAnimationEnd }) => (
          <WaitingRow key={key} item={item} now={now} motion={{ glide: key, arrive: arrival.arrive(key), stagger: arrival.stagger(key), leaving, onAnimationEnd }} />
        ))}
      </ul>
      {total > items.length ? <p className={styles['more']}>And {total - items.length} more.</p> : null}
    </section>
  )
}

function HowItWorks() {
  return (
    <section className={styles['section']} aria-labelledby={HOW_ID}>
      <h2 id={HOW_ID} tabIndex={-1}>
        How it works
      </h2>
      <ol className={styles['steps']}>
        {HOW_IT_WORKS.map(([what, how]) => (
          <li key={what}>
            <div>
              <div className={styles['what']}>{what}</div>
              <div className={styles['how']}>{how}</div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function Loaded({ now, home, next }: { now: Date; home: HomeOut; next: Next | null }) {
  const needs = useMemo(() => needsOf(home), [home])
  const operator = isOperator(useMe().data)
  const dayOne = home.workflows === 0
  const firstWorkflow = dayOne && operator
  const arrival = useArrival([
    ...needs.shown.map((need) => need.key),
    ...home.waiting_on_others.map((item) => `waiting:${item.run_id}`),
    ...home.drafts.map((draft) => `draft:${draft.draft_id}`),
  ])
  const [showHow, setShowHow] = useState(false)
  const focusHow = useFocusWhenReady(showHow, () => document.getElementById(HOW_ID))
  const more = moreWords(needs.more)

  return (
    <>
      {firstWorkflow ? <FirstWorkflow /> : null}
      {firstWorkflow && needs.total === 0 ? null : (
        <section className={cx(styles['section'], arrival.page && styles['arrive'])} aria-labelledby="needs-h">
          <h2 id="needs-h">
            Needs you <Count value={needs.total} />
          </h2>
          {needs.shown.length > 0 ? <NeedsList needs={needs.shown} now={now} arrival={arrival} /> : <AllQuiet next={next} />}
          {more ? <p className={styles['more']}>{more}</p> : null}
        </section>
      )}
      {home.waiting_on_others.length > 0 ? <WaitingList items={home.waiting_on_others} total={home.waiting_on_others_total} now={now} arrival={arrival} /> : null}
      {home.drafts.length > 0 ? (
        <section className={styles['section']} aria-labelledby="drafts-h">
          <h2 id="drafts-h">Your drafts</h2>
          <ul className={styles['rows']}>
            {home.drafts.map((draft, index) => (
              <DraftRow key={draft.draft_id} draft={draft} now={now} arrive={arrival.arrive(`draft:${draft.draft_id}`)} stagger={index} />
            ))}
          </ul>
        </section>
      ) : null}
      {dayOne || showHow ? (
        <HowItWorks />
      ) : (
        <button
          type="button"
          className={styles['linkButton']}
          onClick={() => {
            setShowHow(true)
            focusHow()
          }}
        >
          How it works
        </button>
      )}
    </>
  )
}
