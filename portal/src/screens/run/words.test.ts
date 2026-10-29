import { describe, expect, it } from 'vitest'
import { PRODUCT } from '../../shell/product'
import type { LiveRun } from './liveRun'
import { feedTroubleOf, speakerName } from './words'

describe('the run chat', () => {
  it('names the app by its full name', () => {
    expect(speakerName({ kind: 'app' })).toBe(PRODUCT)
    expect(PRODUCT).toBe('AI Workflow Builder')
  })
})

describe('a run page whose live feed has not brought the first events', () => {
  it('waits quietly while it connects', () => {
    expect(feedTroubleOf({ is: 'connecting' }, 'dev')).toBeNull()
  })

  it('says it is trying again while it reconnects', () => {
    expect(feedTroubleOf({ is: 'reconnecting', attempt: 3, inMs: 2000 }, 'dev')).toEqual({ kind: 'waiting', words: 'Can’t reach the platform yet. Trying again.' })
  })

  it.each([
    [404, 'not_found', 'dev', { kind: 'stop', heading: 'Run not found', lead: 'There is no run at this address.' }],
    [403, 'forbidden', 'dev', { kind: 'stop', heading: 'You can’t see this run', lead: 'This account does not have access to it.' }],
    [401, 'signed_out', 'dev', { kind: 'stop', heading: 'You’re signed out', lead: 'Sign in as one of the demo users, then open the run again.' }],
    [401, 'signed_out', 'oidc', { kind: 'stop', heading: 'You’re signed out', lead: 'Sign in again, then open the run again.' }],
    [0, 'rejected', 'dev', { kind: 'retry', heading: 'We couldn’t load this run', lead: 'Check your connection, or try again in a moment.' }],
  ] as const)('says why when the platform answers %i', (status, reason, signIn, trouble) => {
    const closed: LiveRun['connection'] = { is: 'closed', status, reason }
    expect(feedTroubleOf(closed, signIn)).toEqual(trouble)
  })
})
