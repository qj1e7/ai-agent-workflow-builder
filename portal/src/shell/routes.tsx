import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useParams, useSearchParams } from 'react-router'
import { HomePage } from '../screens/home/HomePage'
import { SettingsPage } from '../screens/settings/SettingsPage'
import type { Icon } from '../ui/icons'
import { ExplainRoute } from '../screens/explain/ExplainPage'
import { WorkflowRoute } from '../screens/workflows/WorkflowPage'
import { WorkflowsPage } from '../screens/workflows/WorkflowsPage'
import { WatchLine } from '../screens/software/WatchLine'
import { howItWorksPath } from '../screens/agents/agents'
import { JIRA_PATH } from '../screens/jira/tickets'
import { HomeIcon, SettingsIcon, TicketIcon, WatchlistIcon, WorkflowsIcon } from './icons'
import { NotFoundPage } from './NotFoundPage'
import { OperatorsNote } from './OperatorsNote'
import { PageHead, PageNote } from './PageHead'
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

export const PAGE_IDS = ['home', 'workflows', 'software', 'jira', 'settings'] as const
export type PageId = (typeof PAGE_IDS)[number]

export const PAGES: Readonly<Record<PageId, PageEntry>> = {
  home: {
    path: '/',
    railLabel: 'Home',
    icon: HomeIcon,
    heading: ({ name, now }) => (name ? `${greeting(now)}, ${name}` : greeting(now)),
    lead: ({ now }) => `${today(now)}.`,
    inRail: true,
  },
  workflows: {
    path: '/workflows',
    railLabel: 'Workflows',
    icon: WorkflowsIcon,
    heading: 'Workflows',
    lead: '',
    inRail: true,
  },
  software: {
    path: '/software',
    railLabel: 'Watchlist',
    icon: WatchlistIcon,
    heading: 'Watchlist',
    lead: 'Everything your team runs, in one list.',
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
const SoftwareRoute = lazy(() => import('../screens/software/SoftwarePage').then((module) => ({ default: module.SoftwareRoute })))
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

/** The rail item marked current: Home only at Home, an item on the addresses under it, and a run or approval page under `ofRun`. */
export function railCurrent(pathname: string, ofRun: PageId): PageId | null {
  if (pathname === PAGES.home.path) return 'home'
  if (under(pathname, PAGES.workflows.path)) return 'workflows'
  if (under(pathname, PAGES.software.path)) return 'software'
  if (under(pathname, '/runs') || under(pathname, '/approvals') || under(pathname, '/setup-approvals')) return ofRun
  return null
}

/** What the rail counts, each from the query its page reads, so a count never disagrees with the page it leads to. */
export interface RailCounts {
  /** Needs you's count, from `needsTotal`, the same as Home's Needs you. */
  readonly needs?: number | undefined
  readonly workflows?: number | undefined
  readonly software?: number | undefined
}

/**
 * Each rail item's count (ADR 0052): Home's is the Needs you count, and Workflows and Watchlist show their totals, how many
 * workflows the team has and how much software is watched. None shows for nothing, or before the numbers have loaded.
 */
export function railCountFor(id: PageId, counts: RailCounts): number | null {
  const count = id === 'home' ? counts.needs : id === 'workflows' ? counts.workflows : id === 'software' ? counts.software : undefined
  return count !== undefined && count > 0 ? count : null
}

/** The item's name with its count: "Home, 2 things need you", or "Workflows, 3 in all". */
export function railNameFor(id: PageId, count: number | null): string | undefined {
  if (count === null) return undefined
  const label = PAGES[id].railLabel
  if (id === 'home') return `${label}, ${count === 1 ? '1 thing needs' : `${String(count)} things need`} you`
  return `${label}, ${String(count)} in all`
}

export function wordsOf(words: Words, context: PageContext): string {
  return typeof words === 'function' ? words(context) : words
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
      <Route
        path={PAGES.software.path}
        element={
          <>
            <PageHead heading={wordsOf(PAGES.software.heading, context)} lead={<WatchLine lead={wordsOf(PAGES.software.lead, context)} />}>
              {context.operator ? null : (
                <PageNote>
                  <OperatorsNote what="the watchlist" />
                </PageNote>
              )}
            </PageHead>
            <Lazy>
              <SoftwareRoute now={context.now} />
            </Lazy>
          </>
        }
      />
      <Route
        path={`${PAGES.software.path}/:softwareId`}
        element={
          <Lazy>
            <SoftwareRoute now={context.now} />
          </Lazy>
        }
      />
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
