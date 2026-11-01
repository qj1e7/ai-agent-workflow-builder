import { Link, NavLink } from 'react-router'
import { isOperator, notOnTheList } from '../api/me'
import { useJiraBrowseUrl } from '../api/ticketLinks'
import type { Me } from '../api/types'
import { cx } from '../ui/cx'
import { Mark, SettingsIcon, TicketIcon } from './icons'
import { Menu } from './Menu'
import { PersonChip } from './PersonChip'
import { PRODUCT, PRODUCT_PREFIX } from './product'
import { PAGES } from './routes'
import { TeamsButton } from './TeamsPanel'
import iconButton from './IconButton.module.css'
import styles from './Header.module.css'

export const JIRA_TITLE = 'Jira, practice copy'

export function Header({ person }: { person: Me | null }) {
  // With a real Jira configured, ticket keys link there and the practice page has nothing to add.
  const practiceJira = useJiraBrowseUrl() === null
  return (
    <header className={styles['header']}>
      <div className={styles['inner']}>
        <Link to={PAGES.home.path} className={cx(styles['brand'])}>
          <Mark />
          <span className={styles['brandText']}>
            <span className={styles['brandAi']}>{PRODUCT_PREFIX}</span>
            {PRODUCT.slice(PRODUCT_PREFIX.length)}
          </span>
        </Link>
        <Menu operator={isOperator(person)} />
        <div className={styles['tools']}>
          {/* Its badge polls runs and Teams messages, which the platform refuses to someone not on the People list. */}
          {notOnTheList(person) ? null : <TeamsButton person={person} />}
          {/* Like Teams, it needs the People list: the platform refuses its tickets to someone who is not on it. */}
          {practiceJira && !notOnTheList(person) ? (
            <NavLink to={PAGES.jira.path} className={cx(iconButton['button'])} aria-label={JIRA_TITLE} title={JIRA_TITLE}>
              <TicketIcon />
              <span className={iconButton['label']}>Jira</span>
            </NavLink>
          ) : null}
          <NavLink to={PAGES.settings.path} className={cx(iconButton['button'])} aria-label="Settings" title="Settings">
            <SettingsIcon />
          </NavLink>
          {person ? <PersonChip person={person} /> : null}
        </div>
      </div>
    </header>
  )
}
