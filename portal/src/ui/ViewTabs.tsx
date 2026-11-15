import { useLocation, useSearchParams } from 'react-router'
import { cx } from './cx'
import styles from './ViewTabs.module.css'

/** The page as the platform tells it, or the same workflow or run as n8n draws it. */
export type View = 'main' | 'n8n'

const PARAM = 'view'

/**
 * The view in the address, as `?view=n8n`, so the Planner can open a page on its In n8n tab and a reload keeps it. A switch replaces
 * the entry, so Back leaves the page rather than stepping through its tabs, and keeps the page's Back to the chat.
 */
export function useView(): readonly [View, (view: View) => void] {
  const [params, setParams] = useSearchParams()
  const { state } = useLocation() as { state: unknown }
  const view: View = params.get(PARAM) === 'n8n' ? 'n8n' : 'main'
  const show = (next: View) => {
    const kept = new URLSearchParams(params)
    if (next === 'n8n') kept.set(PARAM, 'n8n')
    else kept.delete(PARAM)
    setParams(kept, { replace: true, state, preventScrollReset: true })
  }
  return [view, show]
}

interface ViewTabsProps {
  /** The first tab's name: Summary on a workflow, Steps on a run. */
  readonly main: string
  readonly shown: View
  readonly onShow: (view: View) => void
  /** Where the page puts it, which differs between the workflow page and the run page. */
  readonly className?: string | undefined
}

/** The sketch's two-way switch above a page's body, for people with n8n access. */
export function ViewTabs({ main, shown, onShow, className }: ViewTabsProps) {
  const tabs: readonly (readonly [View, string])[] = [
    ['main', main],
    ['n8n', 'In n8n'],
  ]
  return (
    <div className={cx(styles['tabs'], className)} role="group" aria-label="View">
      {tabs.map(([view, label]) => (
        <button key={view} type="button" aria-pressed={shown === view} onClick={() => onShow(view)}>
          {label}
        </button>
      ))}
    </div>
  )
}
