import { lazy, Suspense, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { useHome } from '../../api/homeQueries'
import { useRun, useUseCase, useWatchlist } from '../../api/queries'
import { Button, ButtonLink } from '../../ui/Button'
import { escapeIsFree } from '../../ui/escape'
import { IconChevronLeft } from '../../ui/icons'
import { backTitle, InSidePanel, isWide, wrapTab, type PanelHead, type PanelItem } from '../../ui/sidePanel'
import { cx } from '../../ui/cx'
import { SoftwarePanel } from '../software/SoftwarePanel'
import { softwarePath } from '../software/software'
import { workflowPath } from '../workflows/workflow'
import { WorkflowPanel } from '../workflows/WorkflowPanel'
import { CONNECTIONS_PATH, ConnectionPanel, connectionTitle } from './panels/ConnectionPanel'
import { WatchlistPanel, WorkflowsPanel } from './panels/ListPanel'
import { NeedsPanel } from './panels/NeedsPanel'
import { OpensBeside } from './panels/Opens'
import styles from './SidePanel.module.css'

export const PANEL_ID = 'side-panel'
export const PANEL_HEADING = 'side-panel-h'

/** The run's view brings the run page's line and live feed, which load on demand, as the run page does. So does a request's. */
const RunPanel = lazy(() => import('../run/RunPanel').then((module) => ({ default: module.RunPanel })))
const ApprovalPanel = lazy(() => import('../run/RunPanel').then((module) => ({ default: module.ApprovalPanel })))

const TAB_STOPS = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

/**
 * The bar's title and More details, from the same queries the view reads. The bar is drawn once, so the heading that has focus
 * stays put while the view loads, and the title follows the item.
 */
function useHead(item: PanelItem): PanelHead {
  const useCase = useUseCase(item.kind === 'workflow' ? item.id : '')
  const run = useRun(item.kind === 'run' || item.kind === 'approval' ? item.id : '')
  const watchlist = useWatchlist({ enabled: item.kind === 'software' })
  const home = useHome({ enabled: item.kind === 'connection' })
  switch (item.kind) {
    case 'needs':
      return { title: 'Needs you', page: '/workflows' }
    case 'workflows':
      return { title: 'Workflows', page: '/workflows' }
    case 'watchlist':
      return { title: 'Watchlist', page: '/software' }
    case 'build':
      return { title: 'Build', page: null }
    case 'workflow': {
      const shown = useCase.isError ? undefined : useCase.data
      return shown ? { title: shown.name, page: workflowPath(shown) } : { title: 'Workflow', page: null }
    }
    case 'run':
    case 'approval': {
      const shown = run.isError ? undefined : run.data
      return shown ? { title: shown.use_case_name, page: `/runs/${shown.run_id}` } : { title: item.kind === 'run' ? 'Run' : 'Approval', page: null }
    }
    case 'software': {
      const row = watchlist.data?.software.find((software) => software.id === item.id)
      return row ? { title: row.name, page: softwarePath(row.id) } : { title: 'Software', page: null }
    }
    case 'connection': {
      const connection = home.data?.connections.find((found) => found.id === item.id)
      return { title: connection ? connectionTitle(connection) : 'Connection', page: CONNECTIONS_PATH }
    }
  }
}

interface SidePanelProps {
  readonly item: PanelItem
  /** The item Back returns to, such as the list this one was opened from. */
  readonly back?: PanelItem | null
  readonly now: Date
  /** A window 900 px wide or narrower, where the panel covers the window and the chat behind it waits (spec 3.4). */
  readonly narrow: boolean
  readonly onClose: () => void
  readonly onBack?: () => void
  /** Opens an item from a list in the panel, with the list kept behind it for Back. */
  readonly onOpen?: (item: PanelItem) => void
}

/**
 * One item opened from the chat, as a summary (spec 3.3). Its bar has the title, More details when the item has a page, and
 * Close. Escape closes it too, after anything inside that took the key, and before a message at the bottom of the page. An action
 * inside it keeps it open, back at its top, with focus on its heading.
 */
export function SidePanel({ item, back = null, now, narrow, onClose, onBack, onOpen }: SidePanelProps) {
  const panel = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const head = useHead(item)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const dialogOpen = document.querySelector('dialog[open]') !== null
      if (escapeIsFree(event, dialogOpen)) {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || event.defaultPrevented || dialogOpen || !narrow || !panel.current) return
      const stops = [...panel.current.querySelectorAll<HTMLElement>(TAB_STOPS)].filter((stop) => stop.getClientRects().length > 0)
      const next = wrapTab(stops, document.activeElement, event.shiftKey)
      if (!next) return
      event.preventDefault()
      next.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [narrow, onClose])

  // When the window narrows and the panel becomes a dialog, the chat behind it waits, so focus there moves to the panel.
  useEffect(() => {
    if (narrow && !panel.current?.contains(document.activeElement)) heading.current?.focus({ preventScroll: true })
  }, [narrow])

  const backToTop = useCallback(() => {
    if (body.current) body.current.scrollTop = 0
    heading.current?.focus({ preventScroll: true })
  }, [])

  return (
    <div ref={panel} id={PANEL_ID} className={cx(styles['panel'], isWide(item) && styles['wide'])} data-panel={item.kind} data-wide={isWide(item) || undefined} role={narrow ? 'dialog' : 'complementary'} aria-modal={narrow || undefined} aria-labelledby={PANEL_HEADING}>
      <div className={styles['bar']}>
        <h2 ref={heading} id={PANEL_HEADING} tabIndex={-1}>
          {head.title}
        </h2>
        <div className={styles['btns']}>
          <span className={styles['lefts']}>
            {back && onBack ? (
              <Button icon={IconChevronLeft} onClick={onBack}>
                {backTitle(back)}
              </Button>
            ) : null}
            {head.page ? <ButtonLink to={head.page}>More details</ButtonLink> : null}
          </span>
          <Button onClick={onClose}>Close</Button>
        </div>
      </div>
      <div ref={body} className={styles['body']}>
        <InSidePanel.Provider value={backToTop}>
          <View item={item} now={now} onOpen={onOpen} />
        </InSidePanel.Provider>
      </div>
    </div>
  )
}

function View({ item, now, onOpen }: { item: PanelItem; now: Date; onOpen: ((item: PanelItem) => void) | undefined }) {
  switch (item.kind) {
    case 'needs':
      return beside(item, onOpen, <NeedsPanel now={now} />)
    case 'workflows':
      return beside(item, onOpen, <WorkflowsPanel now={now} />)
    case 'watchlist':
      return beside(item, onOpen, <WatchlistPanel now={now} />)
    case 'workflow':
      return <WorkflowPanel id={item.id} now={now} />
    case 'run':
    case 'approval':
      return (
        <Suspense
          fallback={
            <p className="muted" role="status">
              Loading the run
            </p>
          }
        >
          {item.kind === 'run' ? <RunPanel key={item.id} id={item.id} /> : <ApprovalPanel key={item.id} id={item.id} />}
        </Suspense>
      )
    case 'software':
      return <SoftwarePanel id={item.id} />
    case 'connection':
      return <ConnectionPanel id={item.id} now={now} />
    case 'build':
      return null
  }
}

/** A list in the panel opens its rows in the panel. Without a way to do that, as in a test of one view, they open as pages. */
function beside(item: PanelItem, onOpen: ((item: PanelItem) => void) | undefined, view: ReactNode): ReactNode {
  return onOpen ? (
    <OpensBeside shown={item} onOpen={onOpen}>
      {view}
    </OpensBeside>
  ) : (
    view
  )
}
