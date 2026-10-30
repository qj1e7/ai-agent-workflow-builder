import { NavLink } from 'react-router'
import { cx } from '../ui/cx'
import { MENU_PAGE_IDS, PAGES } from './routes'
import styles from './Menu.module.css'

export function Menu() {
  return (
    <nav className={styles['nav']} aria-label="Main">
      {MENU_PAGE_IDS.map((id) => (
        <NavLink key={id} to={PAGES[id].path} end={id === 'home'} className={cx(styles['link'])}>
          {PAGES[id].menuLabel}
        </NavLink>
      ))}
    </nav>
  )
}

export function TabBar() {
  return (
    <nav className={styles['tabbar']} aria-label="Main">
      {MENU_PAGE_IDS.map((id) => {
        const { path, tabLabel, icon: Icon } = PAGES[id]
        return (
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['tab'])}>
            <Icon size={22} />
            <span>{tabLabel}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}
