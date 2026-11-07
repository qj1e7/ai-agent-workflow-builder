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

/** The count is for the eye. The link's own label carries it for a screen reader, starting with the visible name. */
function countFor(id: PageId, operator: boolean, total: number) {
  return total > 0 && id === needsTab(operator) ? <span className={styles['count']} aria-hidden="true">{total}</span> : null
}

const nameWithCount = (id: PageId, operator: boolean, total: number, name: string) =>
  total > 0 && id === needsTab(operator) ? `${name}, ${total} need you` : undefined

export function Menu({ operator, onList }: MenuProps) {
  const total = useNeedsCount(onList)
  return (
    <nav className={styles['nav']} aria-label="Main">
      {menuFor(operator).map((id) => {
        const { path, menuLabel } = PAGES[id]
        return (
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['link'])} aria-label={nameWithCount(id, operator, total, menuLabel)}>
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
          <NavLink key={id} to={path} end={id === 'home'} className={cx(styles['tab'])} aria-label={nameWithCount(id, operator, total, tabLabel)}>
            <Icon size={22} />
            <span>{tabLabel}</span>
            {countFor(id, operator, total)}
          </NavLink>
        )
      })}
    </nav>
  )
}
