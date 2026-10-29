import { lazy, Suspense, type ReactNode } from 'react'
import { Route, Routes } from 'react-router'
import { AgentsPage } from '../screens/agents/AgentsPage'
import type { Icon } from '../ui/icons'
import { BotIcon, BoxIcon, GridIcon, HomeIcon, SettingsIcon } from './icons'
import { NotFoundPage } from './NotFoundPage'
import { EmptyPage } from './PageHead'
import { greeting, today } from './today'

export interface PageContext {
  readonly name: string | null
  readonly now: Date
}

type Words = string | ((context: PageContext) => string)

export interface PageEntry {
  readonly path: string
  readonly menuLabel: string
  readonly tabLabel: string
  readonly icon: Icon
  readonly heading: Words
  readonly lead: Words
  readonly inMenu: boolean
}

export const PAGE_IDS = ['home', 'workflows', 'software', 'agents', 'settings'] as const
export type PageId = (typeof PAGE_IDS)[number]

export const PAGES: Readonly<Record<PageId, PageEntry>> = {
  home: {
    path: '/',
    menuLabel: 'Home',
    tabLabel: 'Home',
    icon: HomeIcon,
    heading: ({ name, now }) => (name ? `${greeting(now)}, ${name}` : greeting(now)),
    lead: ({ now }) => `${today(now)}.`,
    inMenu: true,
  },
  workflows: {
    path: '/workflows',
    menuLabel: 'Workflows',
    tabLabel: 'Workflows',
    icon: GridIcon,
    heading: 'Workflows',
    lead: 'Your team’s repeated tasks. Each one runs by itself and asks before it changes anything.',
    inMenu: true,
  },
  software: {
    path: '/software',
    menuLabel: 'Software watchlist',
    tabLabel: 'Watchlist',
    icon: BoxIcon,
    heading: 'Software watchlist',
    lead: 'Everything your team runs, in one list. Each check cross-checks versions, support dates and known vulnerabilities across trusted sources, and its upgrade tickets go out in one approval.',
    inMenu: true,
  },
  agents: {
    path: '/agents',
    menuLabel: 'Agent library',
    tabLabel: 'Agents',
    icon: BotIcon,
    heading: 'Agent library',
    lead: 'The agents your team can use. For each workflow, the Planner picks the ones it needs. An agent can use only the tools on its card, and anything that changes data waits for a yes.',
    inMenu: true,
  },
  settings: {
    path: '/settings',
    menuLabel: 'Settings',
    tabLabel: 'Settings',
    icon: SettingsIcon,
    heading: 'Settings',
    lead: 'For whoever looks after the platform. Every change here is recorded with who made it.',
    inMenu: false,
  },
}

const RunRoute = lazy(() => import('../screens/run/RunPage').then((module) => ({ default: module.RunRoute })))
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

export const MENU_PAGE_IDS: readonly PageId[] = PAGE_IDS.filter((id) => PAGES[id].inMenu)

export function wordsOf(words: Words, context: PageContext): string {
  return typeof words === 'function' ? words(context) : words
}

export function AppRoutes({ context }: { context: PageContext }) {
  return (
    <Routes>
      <Route
        path={`${PAGES.agents.path}/:agentId?`}
        element={<AgentsPage heading={wordsOf(PAGES.agents.heading, context)} lead={wordsOf(PAGES.agents.lead, context)} />}
      />
      {PAGE_IDS.filter((id) => id !== 'agents').map((id) => {
        const { path, heading, lead } = PAGES[id]
        return <Route key={id} path={path} element={<EmptyPage heading={wordsOf(heading, context)} lead={wordsOf(lead, context)} />} />
      })}
      <Route path="/runs/:runId" element={<Lazy><RunRoute /></Lazy>} />
      <Route path="/approvals/:approvalId" element={<Lazy><ApprovalRoute /></Lazy>} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
