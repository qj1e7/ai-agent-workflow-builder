import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BlockView } from '../api/types'
import { agentId, planTrack, type Seq, type Stop, type StopCaption, type Track } from '../run'
import { followLayout, layoutKey } from './place'

class StillObserver {
  observe(): void {}
  disconnect(): void {}
}

/** A route with no panels. */
const route = () => ({ querySelectorAll: () => [] }) as unknown as HTMLElement

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('following the layout', () => {
  it('places the line again when the web font arrives, but not once the line is gone', async () => {
    vi.stubGlobal('ResizeObserver', StillObserver)
    const replace = vi.fn()
    let arrive = () => undefined as void
    const fontsReady = new Promise<void>((resolve) => {
      arrive = resolve
    })
    followLayout(route(), replace, fontsReady).stop()
    arrive()
    await fontsReady
    await Promise.resolve()
    expect(replace, 'the font arrived after the line unmounted').not.toHaveBeenCalled()

    const live = followLayout(route(), replace, Promise.resolve())
    await Promise.resolve()
    await Promise.resolve()
    expect(replace, 'the font arrived while the line is up').toHaveBeenCalledTimes(1)
    live.stop()
  })
})

const RELEASE_CHECK: readonly BlockView[] = [
  { key: 'read_releases', name: 'Read GitHub releases', description: "The Release checker reads the repository's releases.", kind: 'agent' },
  { key: 'approval_gate', name: 'Approval gate', description: 'An Approver reviews the proposed ticket in Teams before it is written.', kind: 'approval' },
  { key: 'create_ticket', name: 'Create Jira ticket', description: 'One ticket in the chosen project listing the new releases.', kind: 'write_action' },
]
const PLAN = planTrack(RELEASE_CHECK)

function withStop(track: Track, key: string, change: Partial<Stop>): Track {
  return { ...track, stops: track.stops.map((stop) => (stop.key === key ? { ...stop, ...change } : stop)) }
}

const waiting = (elapsedMs: number): StopCaption => ({ is: 'waiting', elapsedMs, spedUp: true })

describe('when the line is measured again', () => {
  it('not while only the waiting counter ticks, as it does every 50 ms in a replay hold', () => {
    expect(layoutKey(withStop(PLAN, 'gate', { caption: waiting(1_000) }))).toBe(layoutKey(withStop(PLAN, 'gate', { caption: waiting(161_000) })))
  })

  it('whenever the parcel, a caption, a figure, the speech or a panel could have moved', () => {
    const base = withStop(PLAN, 'gate', { caption: waiting(1_000) })
    const checker = { key: 'agent:release_checker', is: 'agent', id: agentId('release_checker'), name: 'Release checker', acting: true, status: 'working' } as const
    const changed: Track[] = [
      { ...base, parcel: { at: 1, before: false, form: { is: 'request' } } },
      { ...base, parcel: { at: 3, before: true, form: { is: 'draft', noun: 'ticket', count: 1 } } },
      withStop(base, 'agent:read_releases', { caption: { is: 'found', items: { is: 'chips', items: ['1.2.16'] } } }),
      withStop(base, 'agent:read_releases', { cast: [checker] }),
      withStop(base, 'agent:read_releases', { state: 'current' }),
      { ...base, speech: { seq: 5 as Seq, stop: 1, speaker: checker.id, name: checker.name, text: 'Two releases are new.' } },
      { ...base, panel: { is: 'approval', stop: 3, approvalId: 'apr_x', step: 0 } },
    ]
    const keys = [base, ...changed].map(layoutKey)
    expect(new Set(keys).size, 'each change gives a new key').toBe(keys.length)
  })
})
