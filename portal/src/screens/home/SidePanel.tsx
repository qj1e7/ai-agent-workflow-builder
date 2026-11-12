import { lazy, Suspense, useEffect, useRef } from 'react'
import { Button, ButtonLink } from '../../ui/Button'
import { escapeCloses, InSidePanel, wrapTab, type PanelItem, type PanelView } from '../../ui/sidePanel'
import { SoftwarePanel } from '../software/SoftwarePanel'
import { WorkflowPanel } from '../workflows/WorkflowPanel'
import styles from './SidePanel.module.css'

export const PANEL_HEADING = 'side-panel-h'

/** The run's view brings the run page's line and live feed, which load on demand, as the run page does. */
const RunPanel = lazy(() => import('../run/RunPanel').then((module) => ({ default: module.RunPanel })))

const TAB_STOPS = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

interface SidePanelProps {
  readonly item: PanelItem
  readonly now: Date
  /** A window 900 px wide or narrower, where the panel covers the window and the chat behind it waits (spec 3.4). */
  readonly narrow: boolean
  readonly onClose: () => void
}

/**
 * One item opened from the chat, as a summary (spec 3.3). Its bar has the title, More details when the item has a page, and
 * Close. Escape closes it too. An action inside it keeps it open, back at its top, with focus on its heading.
 */
export function SidePanel({ item, now, narrow, onClose }: SidePanelProps) {
  const panel = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const dialogOpen = document.querySelector('dialog[open]') !== null
      if (escapeCloses(event, dialogOpen)) {
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

  const backToTop = () => {
    if (body.current) body.current.scrollTop = 0
    heading.current?.focus({ preventScroll: true })
  }

  const frame = (view: PanelView) => (
    <div ref={panel} id="side-panel" className={styles['panel']} role={narrow ? 'dialog' : 'complementary'} aria-modal={narrow || undefined} aria-labelledby={PANEL_HEADING}>
      <div className={styles['bar']}>
        <h2 ref={heading} id={PANEL_HEADING} tabIndex={-1}>
          {view.title}
        </h2>
        <div className={styles['btns']}>
          {view.page ? <ButtonLink to={view.page}>More details</ButtonLink> : <span />}
          <Button onClick={onClose}>Close</Button>
        </div>
      </div>
      <div ref={body} className={styles['body']}>
        <InSidePanel.Provider value={backToTop}>{view.body}</InSidePanel.Provider>
      </div>
    </div>
  )

  switch (item.kind) {
    case 'workflow':
      return (
        <WorkflowPanel key={item.id} id={item.id} now={now}>
          {frame}
        </WorkflowPanel>
      )
    case 'run': {
      const loading = (
        <p className="muted" role="status">
          Loading the run
        </p>
      )
      return (
        <Suspense fallback={frame({ title: 'Run', page: null, body: loading })}>
          <RunPanel key={item.id} id={item.id}>
            {frame}
          </RunPanel>
        </Suspense>
      )
    }
    case 'software':
      return (
        <SoftwarePanel key={item.id} id={item.id}>
          {frame}
        </SoftwarePanel>
      )
  }
}
