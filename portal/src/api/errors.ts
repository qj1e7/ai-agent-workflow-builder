import { ApiError } from './client'
import type { SessionKind } from './session'

/** By sign-in kind. The dev wording is pinned by the demo specs; real sign-in asks for a new sign-in. */
export const SIGNED_OUT_WORDS: Record<SessionKind, string> = {
  dev: 'Sign in as one of the demo users, then try again.',
  oidc: 'Sign in again, then try again.',
}

export const OPEN_RUN_AGAIN_WORDS: Record<SessionKind, string> = {
  dev: 'Sign in as one of the demo users, then open the run again.',
  oidc: 'Sign in again, then open the run again.',
}

const SERVER_TROUBLE = 'The platform had a problem. Try again in a moment.'
const UNREACHABLE = 'The platform could not be reached. Check the connection and try again.'

export function errorWords(error: unknown, signIn: SessionKind): string {
  if (!(error instanceof ApiError)) return UNREACHABLE
  if (error.status === 401) return SIGNED_OUT_WORDS[signIn]
  if (error.status >= 500) return SERVER_TROUBLE
  return error.message
}
