import { Link, useLocation } from 'react-router'
import { useHome } from '../api/homeQueries'
import { notOnTheList } from '../api/me'
import { useJiraBrowseUrl } from '../api/ticketLinks'
import type { Me } from '../api/types'
import { needsTotal } from '../screens/home/home'
import { PersonChip } from './PersonChip'
import { PRODUCT } from './product'
import { PAGES, railCountFor, railCurrent, railNameFor, RAIL_PAGE_IDS, type PageId } from './routes'
import { TeamsButton } from './TeamsPanel'
import styles from './Rail.module.css'

export const JIRA_TITLE = 'Jira, practice copy'

const under = (pathname: string, base: string) => pathname === base || pathname.startsWith(`${base}/`)

interface RailLinkProps {
  readonly id: PageId
  readonly current: boolean
  readonly count?: number | null
  readonly label?: string
  readonly name?: string | undefined
}

/** One way out of the rail, drawn the same for a page, the practice Jira and Settings. */
function RailLink({ id, current, count, label, name }: RailLinkProps) {
  const { path, railLabel, icon: Icon } = PAGES[id]
  return (
    <Link to={path} aria-current={current ? 'page' : undefined} className={styles['item']} aria-label={name} title={name ?? label ?? railLabel}>
      <Icon size={22} />
      <span className={styles['label']}>{label ?? railLabel}</span>
      {count ? (
        <span className={styles['count']} data-tone={id === 'home' ? 'alert' : undefined} aria-hidden="true">
          {count}
        </span>
      ) : null}
    </Link>
  )
}

/**
 * The dark rail (ADR 0052): Home and Workflows, then Teams, the practice Jira, Settings and the person at its foot. A column on
 * the left, and a bar across the top at 860 px and narrower. Home's count is the Needs you count, and Workflows' total comes from
 * the query its page reads, so each agrees with the page it leads to.
 */
export function Rail({ person }: { person: Me | null }) {
  const onList = person !== null && !notOnTheList(person)
  const home = useHome({ enabled: onList })
  // With a real Jira configured, ticket keys link there and the practice page has nothing to add.
  const practiceJira = useJiraBrowseUrl() === null
  const { pathname } = useLocation()
  const current = railCurrent(pathname)
  const counts = { needs: home.data ? needsTotal(home.data) : undefined, workflows: home.data?.workflows }
  return (
    <nav className={styles['rail']} aria-label="Browse">
      <span className={styles['logo']} role="img" aria-label={PRODUCT}>
        AI
      </span>
      <ul className={styles['items']}>
        {RAIL_PAGE_IDS.map((id) => {
          const count = railCountFor(id, counts)
          return (
            <li key={id}>
              <RailLink id={id} current={current === id} count={count} name={railNameFor(id, count)} />
            </li>
          )
        })}
      </ul>
      <div className={styles['foot']}>
        {/* Teams' badge polls runs and Teams messages, and the practice Jira reads tickets: the platform refuses both to someone not on the People list. */}
        {onList ? <TeamsButton person={person} className={styles['item']} labelClassName={styles['label']} countClassName={styles['count']} /> : null}
        {onList && practiceJira ? <RailLink id="jira" current={under(pathname, PAGES.jira.path)} label="Jira" name={JIRA_TITLE} /> : null}
        <RailLink id="settings" current={under(pathname, PAGES.settings.path)} name="Settings" />
        {person ? <PersonChip person={person} /> : null}
      </div>
    </nav>
  )
}
