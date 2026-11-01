export type SignInConfig =
  | { readonly kind: 'dev' }
  | {
      readonly kind: 'oidc'
      readonly authority: string
      readonly clientId: string
      readonly scope: string
    }

export type OidcSignIn = Extract<SignInConfig, { kind: 'oidc' }>

export interface PortalConfig {
  readonly mode: 'live'
  readonly signIn: SignInConfig
  /** Where a ticket is viewed in a real Jira, with {key} for the ticket key. null means the Portal's practice Jira page. */
  readonly jiraBrowseUrl: string | null
}

export class PortalConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PortalConfigError'
  }
}

const LIVE_DEV: PortalConfig = {
  mode: 'live',
  signIn: { kind: 'dev' },
  jiraBrowseUrl: null,
}

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

function parseJiraBrowseUrl(value: unknown): string | null {
  if (value === undefined || value === '') return null
  if (!isHttpUrl(value) || !value.includes('{key}')) throw new PortalConfigError('The jira_browse_url in /config.json is not an absolute http(s) URL with {key} in it.')
  return value
}

export function parseConfig(raw: unknown): PortalConfig {
  if (!isRecord(raw)) return LIVE_DEV
  const jiraBrowseUrl = parseJiraBrowseUrl(raw['jira_browse_url'])
  return {
    mode: 'live',
    signIn: raw['auth'] === undefined ? LIVE_DEV.signIn : parseSignIn(raw['auth']),
    jiraBrowseUrl,
  }
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
