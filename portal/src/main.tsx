import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { App } from './App'
import { ApiError } from './api/client'
import { wallClock, type RunClock } from './api/clock'
import { loadConfig, PortalConfigError, type PortalConfig, type PortalMode } from './api/config'
import { ApiProvider } from './api/context'
import { createDevSession, type Session } from './api/session'
import { ErrorBoundary, ErrorScreen } from './ui/ErrorBoundary'
import { SignInGate } from './ui/SignInGate'
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
  return { fetch: demo.fetch, clock: demo.clock }
}

async function chooseSession(config: PortalConfig): Promise<Session | null> {
  if (config.mode === 'demo' || config.signIn.kind === 'dev') return createDevSession()
  const { bootOidc, oidcClientFor } = await import('./api/oidc')
  const boot = await bootOidc(oidcClientFor(config.signIn, window.location.origin), {
    pathname: window.location.pathname,
    search: window.location.search,
    secure: window.isSecureContext && typeof crypto.subtle !== 'undefined',
    replacePath: (path) => window.history.replaceState(null, '', path),
  })
  return boot.kind === 'session' ? boot.session : null
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
  const config = await loadConfig()
  const platform = await choosePlatform(config.mode)
  const session = await chooseSession(config)
  if (!session) return
  mount(
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ApiProvider mode={config.mode} session={session} fetch={platform.fetch} clock={platform.clock}>
          <BrowserRouter>
            <SignInGate>
              <App />
            </SignInGate>
          </BrowserRouter>
        </ApiProvider>
      </QueryClientProvider>
    </ErrorBoundary>,
  )
}

start().catch((error: unknown) => {
  console.error(error)
  mount(<ErrorScreen message={error instanceof PortalConfigError ? error.message : undefined} />)
})
