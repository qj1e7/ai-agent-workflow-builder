import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useParams, useSearchParams } from 'react-router'
import { HomePage } from '../screens/home/HomePage'
import { SettingsPage } from '../screens/settings/SettingsPage'
import type { Icon } from '../ui/icons'
import { WorkflowRoute } from '../screens/workflows/WorkflowPage'
import { WorkflowsPage } from '../screens/workflows/WorkflowsPage'
import { howItWorksPath } from '../screens/agents/agents'
import { JIRA_PATH } from '../screens/jira/tickets'
import { BoxIcon, ChatIcon, GridIcon, SettingsIcon, TicketIcon } from './icons'
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

export const PAGE_IDS = ['home', 'workflows', 'software', 'jira', 'settings'] as const
export type PageId = (typeof PAGE_IDS)[number]

export const PAGES: Readonly<Record<PageId, PageEntry>> = {
  home: {
    path: '/',
    railLabel: 'Chat',
    icon: ChatIcon,
    heading: ({ name, now }) => (name ? `${greeting(now)}! ${name}` : greeting(now)),
    lead: ({ now }) => `${today(now)}.`,
    inRail: true,
  },
  workflows: {
    path: '/workflows',
    railLabel: 'Workflows',
    icon: GridIcon,
    heading: 'Workflows',
    lead: 'The jobs that run by themselves, such as the Software watchlist, and what needs you.',
    inRail: true,
  },
  software: {
    path: '/software',
    railLabel: 'Watchlist',
    icon: BoxIcon,
    heading: 'Software watchlist',
    lead: 'Everything your team runs, in one list. Each check reads the newest release from GitHub, and its upgrade tickets go out in one approval.',
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

/** The rail item marked current: Chat only at Home, an item on the addresses under it, and a run or approval page under `ofRun`. */
export function railCurrent(pathname: string, ofRun: PageId): PageId | null {
  if (pathname === PAGES.home.path) return 'home'
  if (under(pathname, PAGES.workflows.path)) return 'workflows'
  if (under(pathname, PAGES.software.path)) return 'software'
  if (under(pathname, '/runs') || under(pathname, '/approvals')) return ofRun
  return null
}

export interface RailCount {
  readonly total: number
  readonly says: 'need you' | 'need action'
}

/**
 * Each rail item's count. Workflows holds what needs an Operator, Chat holds it for anyone else, and Watchlist holds what
 * needs action on the list, for someone who can act on it. An Approver who is not an Operator gets no Watchlist count.
 */
export function railCountFor(id: PageId, operator: boolean, needs: number, watch: number): RailCount | null {
  const count: RailCount | null =
    id === 'workflows' && operator ? { total: needs, says: 'need you' }
    : id === 'home' && !operator ? { total: needs, says: 'need you' }
    : id === 'software' && operator ? { total: watch, says: 'need action' }
    : null
  return count !== null && count.total > 0 ? count : null
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
        element={<WorkflowsPage heading={wordsOf(PAGES.workflows.heading, context)} lead={wordsOf(PAGES.workflows.lead, context)} now={context.now} />}
      />
      <Route path={`${PAGES.workflows.path}/:useCaseId`} element={<WorkflowRoute now={context.now} />} />
      <Route path={PAGES.home.path} element={<HomePage heading={wordsOf(PAGES.home.heading, context)} today={wordsOf(PAGES.home.lead, context)} now={context.now} />} />
      <Route
        path={PAGES.software.path}
        element={
          <>
            <PageHead heading={wordsOf(PAGES.software.heading, context)} lead={wordsOf(PAGES.software.lead, context)} />
            <Lazy>
              <SoftwareRoute />
            </Lazy>
          </>
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
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
