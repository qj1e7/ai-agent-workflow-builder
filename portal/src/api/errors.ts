import { ApiError } from './client'

const SIGNED_OUT = 'Sign in as one of the demo users, then try again.'
const SERVER_TROUBLE = 'The platform had a problem. Try again in a moment.'
const UNREACHABLE = 'The platform could not be reached. Check the connection and try again.'

export function errorWords(error: unknown): string {
  if (!(error instanceof ApiError)) return UNREACHABLE
  if (error.status === 401) return SIGNED_OUT
  if (error.status >= 500) return SERVER_TROUBLE
  return error.message
}
