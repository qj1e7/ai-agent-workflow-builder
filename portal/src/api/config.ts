export type PortalMode = 'live' | 'demo'

export interface PortalConfig {
  readonly mode: PortalMode
}

const LIVE: PortalConfig = { mode: 'live' }

export function parseConfig(raw: unknown): PortalConfig {
  if (typeof raw !== 'object' || raw === null) return LIVE
  const mode = (raw as { mode?: unknown }).mode
  return mode === 'demo' ? { mode: 'demo' } : LIVE
}

export async function loadConfig(fetchConfig: typeof fetch = (input, init) => fetch(input, init)): Promise<PortalConfig> {
  try {
    const response = await fetchConfig('/config.json', { cache: 'no-store' })
    if (!response.ok) return LIVE
    return parseConfig(await response.json())
  } catch {
    return LIVE
  }
}
