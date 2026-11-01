import { createContext, useContext, type ReactNode } from 'react'

const BrowseUrl = createContext<string | null>(null)

/** Gives every ticket link the Jira address from /config.json, or null for the practice Jira page. */
export function TicketLinksProvider({ browseUrl, children }: { browseUrl: string | null; children: ReactNode }) {
  return <BrowseUrl.Provider value={browseUrl}>{children}</BrowseUrl.Provider>
}

export function useJiraBrowseUrl(): string | null {
  return useContext(BrowseUrl)
}
