import { NavLink } from 'react-router'
import { useHome } from '../api/homeQueries'
import { needsTotal } from '../screens/home/home'
import { cx } from '../ui/cx'
import { menuFor, needsTab, PAGES, type PageId } from './routes'
import styles from './Menu.module.css'

interface MenuProps {
  readonly operator: boolean
  readonly onList: boolean
}

/** The Needs you count from the same query and the same function as Home and Workflows. */
function useNeedsCount(onList: boolean): number {
  const home = useHome({ enabled: onList })
  return home.data ? needsTotal(home.data) : 0
}

function Count({ total }: { total: number }) {
  return (
    <span className={styles['count']}>
      <span className="visually-hidden">, </span>
      {total}
      <span className="visually-hidden"> need you</span>
    </span>
  )
}

function countFor(id: PageId, operator: boolean, total: number) {
  return total > 0 && id === needsTab(operator) ? <Count total={total} /> : null
}

export function Menu({ operator, onList }: MenuProps) {
  const total = useNeedsCount(onList)
  return (
    <nav className={styles['nav']} aria-label="Main">
      {menuFor(operator).map((id) => {
        const { path, menuLabel, icon: Icon, forOperators } = PAGES[id]
        return (
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['link'], forOperators && styles['new'])}>
            {forOperators ? <Icon size={16} /> : null}
            {menuLabel}
            {countFor(id, operator, total)}
          </NavLink>
        )
      })}
    </nav>
  )
}

export function TabBar({ operator, onList }: MenuProps) {
  const total = useNeedsCount(onList)
  return (
    <nav className={styles['tabbar']} aria-label="Main">
      {menuFor(operator).map((id) => {
        const { path, tabLabel, icon: Icon } = PAGES[id]
        return (
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['tab'])}>
            <Icon size={22} />
            <span>{tabLabel}</span>
            {countFor(id, operator, total)}
          </NavLink>
        )
      })}
    </nav>
  )
}
