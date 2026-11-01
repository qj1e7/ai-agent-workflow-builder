import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { App } from './App'
import { ApiError } from './api/client'
import { loadConfig, PortalConfigError, type PortalConfig } from './api/config'
import { ApiProvider } from './api/context'
import { TicketLinksProvider } from './api/ticketLinks'
import { createDevSession, type Boot } from './api/session'
import { ErrorBoundary, ErrorScreen } from './ui/ErrorBoundary'
import { SignInGate } from './ui/SignInGate'
import './ui/tokens.css'
import './ui/base.css'

async function chooseSession(config: PortalConfig): Promise<Boot> {
  if (config.signIn.kind === 'dev') return { kind: 'session', session: createDevSession() }
  const { bootOidc, oidcClientFor } = await import('./api/oidc')
  return bootOidc(oidcClientFor(config.signIn, window.location.origin), {
    pathname: window.location.pathname,
    search: window.location.search,
    secure: window.isSecureContext && typeof crypto.subtle !== 'undefined',
    replacePath: (path) => window.history.replaceState(null, '', path),
  })
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
  const boot = await chooseSession(config)
  if (boot.kind === 'redirecting') return
  mount(
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ApiProvider session={boot.session} platformFetch={(input, init) => window.fetch(input, init)}>
          <TicketLinksProvider config={config}>
            <BrowserRouter>
              <SignInGate>
                <App />
              </SignInGate>
            </BrowserRouter>
          </TicketLinksProvider>
        </ApiProvider>
      </QueryClientProvider>
    </ErrorBoundary>,
  )
}

start().catch((error: unknown) => {
  console.error(error)
  mount(<ErrorScreen message={error instanceof PortalConfigError ? error.message : undefined} />)
})
