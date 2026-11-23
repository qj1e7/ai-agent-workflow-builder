import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router'
import { HomePage } from '../screens/home/HomePage'
import { SettingsPage } from '../screens/settings/SettingsPage'
import type { Icon } from '../ui/icons'
import { ExplainRoute } from '../screens/explain/ExplainPage'
import { WorkflowRoute } from '../screens/workflows/WorkflowPage'
import { WorkflowsPage } from '../screens/workflows/WorkflowsPage'
import { useWatchlist } from '../api/queries'
import { WATCHLIST_PATH } from '../screens/software/software'
import { howItWorksPath } from '../screens/agents/agents'
import { JIRA_PATH } from '../screens/jira/tickets'
import { ChatIcon, NodesIcon, SettingsIcon, TicketIcon } from './icons'
import { NotFoundPage } from './NotFoundPage'
import { PageHead } from './PageHead'
import { greeting, today } from './today'

export interface PageContext {
  readonly name: string | null
  readonly now: Date
  readonly operator: boolean
}

type Words = string | ((context: PageContext) => string)

export interface PageEntry {
  readonly path: string
  readonly railLabel: string
  readonly icon: Icon
  readonly heading: Words
  readonly lead: Words
  readonly inRail: boolean
}

export const PAGE_IDS = ['home', 'workflows', 'jira', 'settings'] as const
export type PageId = (typeof PAGE_IDS)[number]

export const PAGES: Readonly<Record<PageId, PageEntry>> = {
  home: {
    path: '/',
    railLabel: 'Chat',
    icon: ChatIcon,
    heading: ({ name, now }) => (name ? `${greeting(now)}, ${name}` : greeting(now)),
    lead: ({ now }) => `${today(now)}.`,
    inRail: true,
  },
  workflows: {
    path: '/workflows',
    railLabel: 'Workflows',
    icon: NodesIcon,
    heading: 'Workflows',
    lead: '',
    inRail: true,
  },
  jira: {
    path: JIRA_PATH,
    railLabel: 'Practice Jira',
    icon: TicketIcon,
    heading: 'Practice Jira',
    lead: 'Practice copy. Nothing reaches a real Jira.',
    inRail: false,
  },
  settings: {
    path: '/settings',
    railLabel: 'Settings',
    icon: SettingsIcon,
    heading: 'Settings',
    lead: 'For whoever looks after the platform. Every change here is recorded with who made it.',
    inRail: false,
  },
}

const RunRoute = lazy(() => import('../screens/run/RunPage').then((module) => ({ default: module.RunRoute })))
const JiraRoute = lazy(() => import('../screens/jira/JiraPage').then((module) => ({ default: module.JiraRoute })))
const SetUpApprovalRoute = lazy(() => import('../screens/drafted/SetUpApprovalPage').then((module) => ({ default: module.SetUpApprovalRoute })))
const ApprovalRoute = lazy(() => import('../screens/run/RunPage').then((module) => ({ default: module.ApprovalRoute })))

function Lazy({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <p className="muted" role="status">
          Loading
        </p>
      }
    >
      {children}
    </Suspense>
  )
}

export const RAIL_PAGE_IDS: readonly PageId[] = PAGE_IDS.filter((id) => PAGES[id].inRail)

const under = (pathname: string, base: string) => pathname === base || pathname.startsWith(`${base}/`)

/** The rail item marked current: Chat only at Home, Workflows on the addresses under it, and on a run or approval page, whichever workflow it is. */
export function railCurrent(pathname: string): PageId | null {
  if (pathname === PAGES.home.path) return 'home'
  if (under(pathname, PAGES.workflows.path)) return 'workflows'
  if (under(pathname, '/runs') || under(pathname, '/approvals') || under(pathname, '/setup-approvals')) return 'workflows'
  return null
}

/**
 * Each rail item's count, the same for everyone: the total the sketch shows, how many workflows the team has. What needs
 * the person is the needs strip's and Workflows' number, so the rail never says it too.
 */
export function railCountFor(id: PageId, workflows: number | undefined): number | null {
  const total = id === 'workflows' ? workflows : undefined
  return total !== undefined && total > 0 ? total : null
}

export function wordsOf(words: Words, context: PageContext): string {
  return typeof words === 'function' ? words(context) : words
}

/** Where an old /software address leads: the watchlist's workflow page, with the software it named, or Workflows when there is no watchlist. */
export function softwareDestination(pathname: string, watchlistId: string | null): string {
  if (watchlistId === null) return PAGES.workflows.path
  const page = `${PAGES.workflows.path}/${watchlistId}`
  const rest = pathname.slice(WATCHLIST_PATH.length).replace(/^\/+|\/+$/g, '')
  return rest === '' ? page : `${page}?software=${rest}`
}

/** The Software page is the watchlist's workflow page now. It takes every address under /software there, once the watchlist is known. */
function OldSoftwareAddress() {
  const { pathname } = useLocation()
  const watchlist = useWatchlist()
  if (watchlist.isPending) {
    return (
      <p className="muted" role="status">
        Loading
      </p>
    )
  }
  return <Navigate to={softwareDestination(pathname, watchlist.data?.use_case_id ?? null)} replace />
}

const OLD_NEW_PATH = '/new'
const OLD_AGENTS_PATH = '/agents'

/** The old New workflow address, and a saved draft's old link: both lead to Home, which reopens the draft as the Planner's card. */
function OldNewAddress() {
  const [search] = useSearchParams()
  const draft = search.get('draft')
  return <Navigate to={draft ? `${PAGES.home.path}?draft=${encodeURIComponent(draft)}` : PAGES.home.path} replace />
}

/** The Agent library is now How it works in Settings. An agent's address and tab carry over for an Operator, and anyone else goes Home. */
export function oldAgentsDestination(operator: boolean, agentId: string | null, tab: string | null): string {
  return operator ? howItWorksPath({ show: tab, agent: agentId }) : PAGES.home.path
}

function OldAgentsAddress({ operator }: { operator: boolean }) {
  const { agentId = null } = useParams()
  const [search] = useSearchParams()
  return <Navigate to={oldAgentsDestination(operator, agentId, search.get('tab'))} replace />
}

export function AppRoutes({ context }: { context: PageContext }) {
  return (
    <Routes>
      <Route path={`${OLD_AGENTS_PATH}/:agentId?`} element={<OldAgentsAddress operator={context.operator} />} />
      <Route
        path={PAGES.workflows.path}
        element={<WorkflowsPage heading={wordsOf(PAGES.workflows.heading, context)} now={context.now} />}
      />
      <Route path={`${PAGES.workflows.path}/:useCaseId`} element={<WorkflowRoute now={context.now} />} />
      <Route path={`${PAGES.workflows.path}/:useCaseId/explain`} element={<ExplainRoute />} />
      <Route path={PAGES.home.path} element={<HomePage greeting={wordsOf(PAGES.home.heading, context)} today={wordsOf(PAGES.home.lead, context)} now={context.now} />} />
      <Route path={`${WATCHLIST_PATH}/*`} element={<OldSoftwareAddress />} />
      <Route
        path={`${PAGES.jira.path}/:key?`}
        element={
          <>
            <PageHead heading={wordsOf(PAGES.jira.heading, context)} lead={wordsOf(PAGES.jira.lead, context)} />
            <Lazy>
              <JiraRoute />
            </Lazy>
          </>
        }
      />
      <Route path={PAGES.settings.path} element={<SettingsPage heading={wordsOf(PAGES.settings.heading, context)} lead={wordsOf(PAGES.settings.lead, context)} now={context.now} />} />
      <Route path={`${OLD_NEW_PATH}/*`} element={<OldNewAddress />} />
      <Route path="/runs/:runId" element={<Lazy><RunRoute /></Lazy>} />
      <Route path="/approvals/:approvalId" element={<Lazy><ApprovalRoute /></Lazy>} />
      <Route path="/setup-approvals/:approvalId" element={<Lazy><SetUpApprovalRoute /></Lazy>} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
