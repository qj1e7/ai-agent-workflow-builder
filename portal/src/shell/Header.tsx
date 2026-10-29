import { Link, NavLink } from 'react-router'
import type { Me } from '../api/types'
import { cx } from '../ui/cx'
import { Mark, SettingsIcon } from './icons'
import { Menu } from './Menu'
import { PersonChip } from './PersonChip'
import { PAGES } from './routes'
import { TeamsButton } from './TeamsPanel'
import iconButton from './IconButton.module.css'
import styles from './Header.module.css'

export function Header({ person }: { person: Me | null }) {
  return (
    <header className={styles['header']}>
      <div className={styles['inner']}>
        <Link to={PAGES.home.path} className={cx(styles['brand'])}>
          <Mark />
          <span className={styles['brandText']}>
            <span className={styles['brandAi']}>AI </span>Workflow Builder
          </span>
        </Link>
        <Menu />
        <div className={styles['tools']}>
          <TeamsButton />
          <NavLink to={PAGES.settings.path} className={cx(iconButton['button'])} aria-label="Settings" title="Settings">
            <SettingsIcon />
          </NavLink>
          {person ? <PersonChip person={person} /> : null}
        </div>
      </div>
    </header>
  )
}
