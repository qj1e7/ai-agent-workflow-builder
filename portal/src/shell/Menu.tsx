import { NavLink } from 'react-router'
import { cx } from '../ui/cx'
import { menuFor, PAGES } from './routes'
import styles from './Menu.module.css'

export function Menu({ operator }: { operator: boolean }) {
  return (
    <nav className={styles['nav']} aria-label="Main">
      {menuFor(operator).map((id) => {
        const { path, menuLabel, icon: Icon, forOperators } = PAGES[id]
        return (
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['link'], forOperators && styles['new'])}>
            {forOperators ? <Icon size={16} /> : null}
            {menuLabel}
          </NavLink>
        )
      })}
    </nav>
  )
}

export function TabBar({ operator }: { operator: boolean }) {
  return (
    <nav className={styles['tabbar']} aria-label="Main">
      {menuFor(operator).map((id) => {
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
