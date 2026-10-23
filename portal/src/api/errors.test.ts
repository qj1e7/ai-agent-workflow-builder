import { describe, expect, it } from 'vitest'
import { ApiError } from './client'
import { errorWords } from './errors'
import { displayName } from './people'

describe('errorWords', () => {
  it('shows the platform own message for a refusal the person can act on', () => {
    expect(errorWords(new ApiError(404, { message: 'There is no such use case.' }))).toBe('There is no such use case.')
  })

  it('tells the person to sign in on a 401', () => {
    expect(errorWords(new ApiError(401, { message: 'x' }))).toMatch(/sign in/i)
  })

  it('does not leak server internals on a 500', () => {
    expect(errorWords(new ApiError(500, { detail: 'Traceback (most recent call last)' }))).toBe(
      'The platform had a problem. Try again in a moment.',
    )
  })

  it('says the platform is unreachable when the request never got an answer', () => {
    expect(errorWords(new TypeError('Failed to fetch'))).toMatch(/could not be reached/)
  })
})

describe('displayName', () => {
  const users = [{ id: 'bob', display: 'Bob', roles: ['approver' as const] }]

  it('uses the name the platform gives', () => {
    expect(displayName(users, 'bob')).toBe('Bob')
  })

  it('falls back to a readable name while users load or when one is unknown', () => {
    expect(displayName(undefined, 'alice')).toBe('Alice')
    expect(displayName(users, 'dana_lee')).toBe('Dana lee')
  })
})
