export type PortalMode = 'live' | 'demo'

export type SignInConfig =
  | { readonly kind: 'dev' }
  | { readonly kind: 'oidc'; readonly authority: string; readonly clientId: string; readonly scope: string }

export type OidcSignIn = Extract<SignInConfig, { kind: 'oidc' }>

export type PortalConfig = { readonly mode: 'demo' } | { readonly mode: 'live'; readonly signIn: SignInConfig }

/** The platform served a /config.json that names a sign-in the Portal cannot use. Never falls back to dev sign-in. */
export class PortalConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PortalConfigError'
  }
}

const LIVE_DEV: PortalConfig = { mode: 'live', signIn: { kind: 'dev' } }
const DEMO: PortalConfig = { mode: 'demo' }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isHttpUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}

function parseSignIn(auth: unknown): SignInConfig {
  if (!isRecord(auth)) throw new PortalConfigError('The sign-in settings in /config.json are not an object.')
  const { authority, client_id: clientId, scope } = auth
  if (!isHttpUrl(authority)) throw new PortalConfigError('The sign-in authority in /config.json is not an absolute http(s) URL.')
  if (typeof clientId !== 'string' || clientId === '') throw new PortalConfigError('The sign-in client_id in /config.json is empty.')
  if (typeof scope !== 'string' || !scope.split(' ').includes('openid')) {
    throw new PortalConfigError('The sign-in scope in /config.json does not include openid.')
  }
  return { kind: 'oidc', authority, clientId, scope }
}

/** Reads the body nginx serves at /config.json. Anything unreadable is live dev, as before; a present but unusable `auth` is an error. */
export function parseConfig(raw: unknown): PortalConfig {
  if (!isRecord(raw)) return LIVE_DEV
  const hasAuth = raw['auth'] !== undefined
  if (raw['mode'] === 'demo') {
    if (hasAuth) throw new PortalConfigError('Demo mode cannot have sign-in settings in /config.json.')
    return DEMO
  }
  return hasAuth ? { mode: 'live', signIn: parseSignIn(raw['auth']) } : LIVE_DEV
}

export async function loadConfig(fetchConfig: typeof fetch = (input, init) => fetch(input, init)): Promise<PortalConfig> {
  let raw: unknown
  try {
    const response = await fetchConfig('/config.json', { cache: 'no-store' })
    if (!response.ok) return LIVE_DEV
    raw = await response.json()
  } catch {
    return LIVE_DEV
  }
  return parseConfig(raw)
}
