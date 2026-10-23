import { useEffect, useRef, type MouseEvent } from 'react'
import { Link, Outlet, useLocation } from 'react-router'
import { usePortalMode } from '../api/context'
import { cx } from './cx'
import { ErrorBoundary } from './ErrorBoundary'
import { IconChat, IconFlow, IconReplay, IconShield, IconTicket, IconWave, PortalMark, type Icon } from './icons'
import { ThemeToggle } from './ThemeToggle'
import { UserSwitcher } from './UserSwitcher'
import styles from './AppShell.module.css'

interface NavItem {
  label: string
  to: string
  icon: Icon
  isCurrent: (path: string) => boolean
}

const startsWith = (prefix: string) => (path: string) => path === prefix || path.startsWith(`${prefix}/`)

export const NAV_ITEMS: readonly NavItem[] = [
  { label: 'Runs', to: '/', icon: IconWave, isCurrent: (path) => path === '/' || startsWith('/runs')(path) },
  { label: 'Builder', to: '/builder', icon: IconFlow, isCurrent: startsWith('/builder') },
  { label: 'Approvals', to: '/approvals', icon: IconShield, isCurrent: startsWith('/approvals') },
  { label: 'Teams', to: '/teams', icon: IconChat, isCurrent: startsWith('/teams') },
  { label: 'Jira', to: '/jira', icon: IconTicket, isCurrent: startsWith('/jira') },
]

function useHeadingFocus(): void {
  const { pathname } = useLocation()
  const previous = useRef<string | null>(null)

  useEffect(() => {
    const moved = previous.current !== null && previous.current !== pathname
    previous.current = pathname
    const main = document.getElementById('main')
    if (!main) return

    const arrive = (heading: HTMLElement) => {
      document.title = heading.textContent ? `${heading.textContent} - Portal` : 'Portal'
      if (!moved) return
      heading.tabIndex = -1
      heading.focus({ preventScroll: true })
      window.scrollTo(0, 0)
    }

    const found = main.querySelector('h1')
    if (found) {
      arrive(found)
      return
    }
    const observer = new MutationObserver(() => {
      const heading = main.querySelector('h1')
      if (!heading) return
      observer.disconnect()
      arrive(heading)
    })
    observer.observe(main, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [pathname])
}

export function AppShell() {
  const mode = usePortalMode()
  const { pathname } = useLocation()
  useHeadingFocus()

  function skipToMain(event: MouseEvent) {
    event.preventDefault()
    document.getElementById('main')?.focus()
  }

  return (
    <div className={styles['shell']}>
      <a href="#main" className={styles['skip']} onClick={skipToMain}>
        Skip to main content
      </a>
      <header className={styles['header']}>
        <Link to="/" className={styles['brand']}>
          <PortalMark />
          <span className={styles['brandName']}>Portal</span>
        </Link>
        <nav className={styles['nav']} aria-label="Main">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={styles['navLink']}
              aria-current={item.isCurrent(pathname) ? 'page' : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className={styles['tools']}>
          {mode === 'demo' ? (
            <span className={styles['demo']}>
              <IconReplay size={16} />
              Demo data
            </span>
          ) : null}
          <ThemeToggle />
          <UserSwitcher />
        </div>
      </header>
      <main id="main" tabIndex={-1} className={styles['main']}>
        <ErrorBoundary resetKey={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <nav className={styles['tabBar']} aria-label="Main">
        {NAV_ITEMS.map((item) => {
          const current = item.isCurrent(pathname)
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cx(styles['tab'], current && styles['tabCurrent'])}
              aria-current={current ? 'page' : undefined}
            >
              <item.icon size={22} />
              <span>{item.label}</span>
            </Link>
          )
        })}
      </nav>
    </div>
  )
}
