import { createContext, useContext, type ReactNode } from 'react'
import { useWatchlist } from '../api/queries'

/**
 * The watchlist's workflow page id, null when there is no watchlist, and undefined while that is not known. /software is only an old
 * address that redirects to the watchlist's workflow page, so a link to software goes straight there once the id is known.
 */
export const SoftwareLinks = createContext<string | null | undefined>(undefined)

const SOFTWARE_ADDRESS = /^\/software(?:\/([^/?#]+))?\/?$/

/** Where a link to /software or /software/{id} really goes. Any other address, and any address before the watchlist is known, stays as it is. */
export function softwareLinkTarget(to: string, watchlistId: string | null | undefined): string {
  const named = SOFTWARE_ADDRESS.exec(to)
  if (!named || watchlistId === undefined) return to
  if (watchlistId === null) return '/workflows'
  const page = `/workflows/${encodeURIComponent(watchlistId)}`
  const id = named[1]
  return id === undefined ? page : `${page}?${new URLSearchParams({ software: decodeURIComponent(id) }).toString()}`
}

export function useSoftwareTarget(): (to: string) => string {
  const watchlistId = useContext(SoftwareLinks)
  return (to) => softwareLinkTarget(to, watchlistId)
}

export function SoftwareLinksProvider({ children }: { children: ReactNode }) {
  const watchlist = useWatchlist()
  const known = watchlist.isSuccess ? (watchlist.data?.use_case_id ?? null) : undefined
  return <SoftwareLinks.Provider value={known}>{children}</SoftwareLinks.Provider>
}
