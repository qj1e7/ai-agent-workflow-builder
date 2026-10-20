import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { App } from './App'
import { ApiError } from './api/client'
import { wallClock, type RunClock } from './api/clock'
import { loadConfig, type PortalMode } from './api/config'
import { ApiProvider } from './api/context'
import { ErrorBoundary, ErrorScreen } from './ui/ErrorBoundary'
import './ui/tokens.css'
import './ui/base.css'

interface Platform {
  fetch: typeof fetch
  clock: RunClock
}

async function choosePlatform(mode: PortalMode): Promise<Platform> {
  if (mode === 'live') return { fetch: (input, init) => window.fetch(input, init), clock: wallClock }
  const { createDemoPlatform } = await import('./mock')
  const demo = createDemoPlatform()
  return { fetch: demo.fetch, clock: demo.now }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failures, error) => failures < 2 && !(error instanceof ApiError && error.status < 500),
    },
  },
})

function mount(tree: ReactNode): void {
  const container = document.getElementById('root')
  if (container) createRoot(container).render(<StrictMode>{tree}</StrictMode>)
}

async function start(): Promise<void> {
  const { mode } = await loadConfig()
  const platform = await choosePlatform(mode)
  mount(
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ApiProvider mode={mode} fetch={platform.fetch} clock={platform.clock}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ApiProvider>
      </QueryClientProvider>
    </ErrorBoundary>,
  )
}

start().catch((error: unknown) => {
  console.error(error)
  mount(<ErrorScreen />)
})
