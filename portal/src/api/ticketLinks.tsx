import { createContext, useContext, type ReactNode } from 'react'
import type { PortalConfig } from './config'

const BrowseUrl = createContext<string | null>(null)

/** Gives every ticket link the Jira address from /config.json, or null for the practice Jira page. */
export function TicketLinksProvider({ config, children }: { config: Pick<PortalConfig, 'jiraBrowseUrl'>; children: ReactNode }) {
  return <BrowseUrl.Provider value={config.jiraBrowseUrl}>{children}</BrowseUrl.Provider>
}

export function useJiraBrowseUrl(): string | null {
  return useContext(BrowseUrl)
}
