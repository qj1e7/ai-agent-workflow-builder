import { describe, expect, it } from 'vitest'
import { bannerRepeatsThePage } from './Banner'
import type { Banner } from './workflow'

const banner = (change: Partial<Banner>): Banner => ({ tone: 'off', text: 'x', action: null, ...change })

describe('a banner that repeats the page', () => {
  it('goes for an On workflow, a pause and a stop or a wait, whose action moves to the title row', () => {
    expect(bannerRepeatsThePage(banner({ tone: 'ok' }), { state: 'on' })).toBe(true)
    expect(bannerRepeatsThePage(banner({ tone: 'off' }), { state: 'paused' })).toBe(true)
    expect(bannerRepeatsThePage(banner({ tone: 'bad', action: { kind: 'open', runId: 'r' } }), { state: 'on' })).toBe(true)
    expect(bannerRepeatsThePage(banner({ tone: 'wait', action: { kind: 'decide', runId: 'r' } }), { state: 'on' })).toBe(true)
    expect(bannerRepeatsThePage(banner({ tone: 'off', action: { kind: 'resume' } }), { state: 'paused' })).toBe(true)
  })

  it('stays for a workflow deleted in n8n, even while paused, since nothing else says it', () => {
    expect(bannerRepeatsThePage(banner({ tone: 'off' }), { state: 'paused', deleted_in_n8n_at: '2026-11-04T00:00:00Z' })).toBe(false)
  })

  it('stays for a refused write, a version that needs a fix and a workflow that could not move', () => {
    expect(bannerRepeatsThePage(banner({ tone: 'bad', action: { kind: 'yes' } }), { state: 'on' })).toBe(false)
    expect(bannerRepeatsThePage(banner({ tone: 'bad' }), { state: 'on' })).toBe(false)
    expect(bannerRepeatsThePage(banner({ tone: 'bad' }), { state: 'paused' })).toBe(false)
  })
})
