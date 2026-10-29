import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router'
import { useMe } from './api/queries'
import { AskToBeAdded } from './shell/AskToBeAdded'
import { Header } from './shell/Header'
import { TabBar } from './shell/Menu'
import { PlatformDown, platformIsDown } from './shell/PlatformDown'
import { PRODUCT } from './shell/product'
import { AppRoutes } from './shell/routes'
import { TestControls } from './shell/TestControls'
import { ErrorBoundary } from './ui/ErrorBoundary'
import styles from './shell/Shell.module.css'

/** Focus stays where it is on first load, so the skip link stays the first Tab stop. */
function useHeadingFocus(): void {
  const { pathname } = useLocation()
  const previous = useRef<string | null>(null)
  useEffect(() => {
    const heading = document.querySelector<HTMLElement>('main h1')
    if (!heading) return
    document.title = `${heading.textContent.trim()} · ${PRODUCT}`
    if (previous.current !== null && previous.current !== pathname) heading.focus({ preventScroll: true })
    previous.current = pathname
  })
}

function skipToMain(): void {
  const main = document.getElementById('main')
  const target = main?.querySelector<HTMLElement>('h1') ?? main
  target?.focus()
}

export function App({ now = () => new Date() }: { now?: () => Date }) {
  const me = useMe()
  const { pathname } = useLocation()
  useHeadingFocus()

  let content
  if (me.isPending) content = <p className="muted" role="status">Loading</p>
  else if (me.isError && platformIsDown(me.error)) content = <PlatformDown onRetry={() => void me.refetch()} />
  else if (me.data?.on_list === false) content = <AskToBeAdded display={me.data.display} />
  else content = <AppRoutes context={{ name: me.data?.display ?? null, now: now() }} />

  return (
    <>
      <button type="button" className={styles['skip']} onClick={skipToMain}>
        Skip to main content
      </button>
      <Header person={me.data ?? null} />
      <main id="main" tabIndex={-1} className={styles['sheet']}>
        <div className={styles['wrap']}>
          <ErrorBoundary resetKey={pathname}>{content}</ErrorBoundary>
        </div>
      </main>
      <TabBar />
      <TestControls />
    </>
  )
}
