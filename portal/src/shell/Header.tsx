import { Link, NavLink } from 'react-router'
import { isOperator } from '../api/me'
import type { Me } from '../api/types'
import { cx } from '../ui/cx'
import { Mark, SettingsIcon } from './icons'
import { Menu } from './Menu'
import { PersonChip } from './PersonChip'
import { PRODUCT, PRODUCT_PREFIX } from './product'
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
            <span className={styles['brandAi']}>{PRODUCT_PREFIX}</span>
            {PRODUCT.slice(PRODUCT_PREFIX.length)}
          </span>
        </Link>
        <Menu operator={isOperator(person)} />
        <div className={styles['tools']}>
          <TeamsButton person={person} />
          <NavLink to={PAGES.settings.path} className={cx(iconButton['button'])} aria-label="Settings" title="Settings">
            <SettingsIcon />
          </NavLink>
          {person ? <PersonChip person={person} /> : null}
        </div>
      </div>
    </header>
  )
}
