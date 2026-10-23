import { describe, expect, it } from 'vitest'
import type { DevUser, ModelSettingsView } from '../api/types'
import { DemoModelSettings } from './settings'

const ALICE: DevUser = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: DevUser = { id: 'bob', display: 'Bob', roles: ['approver'] }
const CAROL: DevUser = { id: 'carol', display: 'Carol', roles: ['operator'] }
const KEY = 'sk-example-key-not-real-x7'
const WALL = Date.UTC(2026, 10, 2, 6, 2)

async function body(response: Response): Promise<Record<string, unknown>> {
  return (await response.json()) as Record<string, unknown>
}

function viewOf(settings: DemoModelSettings, user: DevUser): ModelSettingsView {
  return settings.view(user)
}

function saveAisg(settings: DemoModelSettings, model = 'claude-haiku-5-5', key: string | null = KEY) {
  const keyPart = key === null ? { use_saved_key: true } : { api_key: key, use_saved_key: false }
  return settings.save(ALICE, { style: 'anthropic', base_url: 'https://llm-gateway.aisg.sg', model, ...keyPart }, WALL)
}

describe('the demo model settings', () => {
  it('starts with nothing set, and only Operators may change it', () => {
    const settings = new DemoModelSettings()
    expect(viewOf(settings, ALICE)).toMatchObject({ available: true, you_can_change: true, active: null, pending: null })
    expect(viewOf(settings, BOB).you_can_change).toBe(false)
  })

  it('finds the models a key can use at a known provider', async () => {
    const answer = await body(new DemoModelSettings().connect(ALICE, { provider_id: 'aisg', api_key: KEY, use_saved_key: false }))
    expect(answer['status']).toBe('connected')
    expect(answer['style']).toBe('anthropic')
    expect((answer['models'] as unknown[]).length).toBe(3)
  })

  it('refuses a short key, a plain http address and an address inside the network, in the platform words', async () => {
    const settings = new DemoModelSettings()
    const short = await body(settings.connect(ALICE, { provider_id: 'aisg', api_key: 'short', use_saved_key: false }))
    const http = await body(settings.connect(ALICE, { base_url: 'http://ai.example', api_key: KEY, use_saved_key: false }))
    const inside = await body(settings.connect(ALICE, { base_url: 'https://localhost/v1', api_key: KEY, use_saved_key: false }))
    expect([short['reason'], http['reason'], inside['reason']]).toEqual(['key_refused', 'address_not_allowed', 'address_not_allowed'])
  })

  it('saves a tested model at a known provider and logs it in plain words', async () => {
    const settings = new DemoModelSettings()
    expect(await body(saveAisg(settings))).toMatchObject({ status: 'saved' })
    const view = viewOf(settings, ALICE)
    expect(view.active).toMatchObject({ model: 'claude-haiku-5-5', key_hint: 'x7', provider: 'AI Singapore gateway' })
    expect(view.changes[0]?.summary).toBe('Alice turned on claude-haiku-5-5 (AI Singapore gateway), with a key ending in x7.')
  })

  it('refuses a model slower than the summary waits for', async () => {
    const settings = new DemoModelSettings()
    const answer = await body(
      settings.save(ALICE, { style: 'openai', base_url: 'https://ai.example/v1', model: 'chat-large', api_key: KEY, use_saved_key: false }, WALL),
    )
    expect(answer).toMatchObject({ status: 'problem', reason: 'too_slow' })
    expect(viewOf(settings, ALICE).pending).toBeNull()
  })

  it('keeps a new address waiting until another Approver confirms the entry they saw', async () => {
    const settings = new DemoModelSettings()
    saveAisg(settings)
    const asked = settings.save(
      ALICE,
      { style: 'openai', base_url: 'https://ai-gateway.ncs.example/v1', model: 'ncs-llm-small', api_key: KEY, use_saved_key: false },
      WALL,
    )
    expect(await body(asked)).toMatchObject({ status: 'awaiting_confirmation' })
    const pending = viewOf(settings, BOB).pending
    expect(pending).toMatchObject({ you_can_decide: true, model: 'ncs-llm-small' })
    expect(viewOf(settings, ALICE).pending?.why_not).toBe('You entered this address, so another Approver must confirm it.')
    expect(viewOf(settings, CAROL).pending?.why_not).toBe('Only an Approver can confirm an address.')

    expect(settings.decide(ALICE, { verdict: 'confirm', digest: pending?.digest }, WALL).status).toBe(403)
    expect(settings.decide(BOB, { verdict: 'confirm', digest: 'demo-stale' }, WALL).status).toBe(409)
    expect(settings.decide(BOB, { verdict: 'confirm', digest: pending?.digest }, WALL).status).toBe(200)
    expect(viewOf(settings, BOB).active?.model).toBe('ncs-llm-small')
    expect(viewOf(settings, BOB).changes[0]?.summary).toBe('Bob confirmed ai-gateway.ncs.example. Runs now use ncs-llm-small.')
  })

  it('reuses the saved key only at the host it was saved for', () => {
    const settings = new DemoModelSettings()
    saveAisg(settings)
    expect(saveAisg(settings, 'claude-sonnet-5-5', null).status).toBe(200)
    const elsewhere = settings.connect(ALICE, { provider_id: 'openai', use_saved_key: true })
    expect(elsewhere.status).toBe(409)
  })

  it('deletes the key when the model is turned off', () => {
    const settings = new DemoModelSettings()
    saveAisg(settings)
    expect(settings.turnOff(ALICE, WALL).status).toBe(204)
    expect(viewOf(settings, ALICE).active).toBeNull()
    expect(viewOf(settings, ALICE).changes[0]?.summary).toBe('Alice turned the AI model off, and the saved key was deleted.')
  })

  it('refuses changes from someone who is not an Operator', () => {
    const settings = new DemoModelSettings()
    expect(settings.connect(BOB, { provider_id: 'aisg', api_key: KEY, use_saved_key: false }).status).toBe(403)
    expect(settings.turnOff(BOB, WALL).status).toBe(403)
    expect(settings.decide(CAROL, { verdict: 'confirm', digest: 'x' }, WALL).status).toBe(403)
  })
})
