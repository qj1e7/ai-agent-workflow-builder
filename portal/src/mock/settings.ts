import connected from '@contracts/fixtures/settings/connect.connected.json'
import empty from '@contracts/fixtures/settings/model.empty.json'
import type {
  Connected,
  DevUser,
  FoundModel,
  ModelChangeOut,
  ModelOut,
  ModelProblem,
  ModelSettingsView,
  PendingModelOut,
} from '../api/types'
import { invalid, isRecord, json, problem } from './http'

// The demo plays the platform's settings in the browser. It keeps no key, only its last two characters.
const PROVIDERS = (empty as ModelSettingsView).providers
const AISG_MODELS = (connected as Connected).models
const SENTENCE = 'Two new LangGraph releases came out after 1.2.14: 1.2.16 and 1.2.15.'
const INSIDE = /^(localhost|127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/
const SUMMARY_WAIT_SECONDS = 10
const KEY_REFUSED = 'The address answered, but it refused this key. Check that you copied all of it.'
const OWN_ADDRESS = 'You entered this address, so another Approver must confirm it.'

interface Pending {
  readonly entry: ModelOut
  readonly digest: string
}

function hostOf(address: string): string {
  try {
    return new URL(address).hostname.toLowerCase()
  } catch {
    return ''
  }
}

function models(...entries: [string, boolean][]): FoundModel[] {
  return entries.map(([id, suggested]) => ({ id, display: id, suggested }))
}

function refusal(reason: ModelProblem['reason'], message: string): ModelProblem {
  return { status: 'problem', reason, message }
}

function addressProblem(address: string): ModelProblem | null {
  const host = hostOf(address)
  if (!host) return refusal('address_not_allowed', 'Use a plain address such as https://api.example.com/v1.')
  if (!address.startsWith('https://')) {
    return refusal(
      'address_not_allowed',
      'Use an address that starts with https://. Plain http is allowed only for addresses the deployment lists.',
    )
  }
  if (INSIDE.test(host)) {
    return refusal(
      'address_not_allowed',
      `${host} is inside a private network, and the deployment does not list it. Ask the team to add it.`,
    )
  }
  return null
}

function detect(address: string): Connected {
  const host = hostOf(address)
  const base = address.replace(/\/+$/, '')
  if (host === 'llm-gateway.aisg.sg') return { status: 'connected', style: 'anthropic', base_url: base, models: AISG_MODELS }
  if (host === 'api.anthropic.com') {
    return { status: 'connected', style: 'anthropic', base_url: base, models: AISG_MODELS.slice(0, 2) }
  }
  const list =
    host === 'api.openai.com'
      ? models(['gpt-5-mini', true], ['gpt-5', false])
      : host === 'generativelanguage.googleapis.com'
        ? models(['gemini-2.5-flash', true], ['gemini-2.5-pro', false])
        : host.includes('ncs')
          ? models(['ncs-llm-small', true], ['ncs-llm-large', false])
          : models(['chat-small', true], ['chat-large', false])
  return { status: 'connected', style: 'openai', base_url: base, models: list }
}

function secondsFor(model: string): number {
  if (model === 'chat-large') return 11.2
  return /haiku|mini|flash|small/.test(model) ? 1.4 : 3.2
}

function isOperator(user: DevUser): boolean {
  return user.roles.includes('operator')
}

const OPERATORS_ONLY = 'Only an Operator can do this. Ask an Operator on the team.'

export class DemoModelSettings {
  private active: ModelOut | null = null
  private pending: Pending | null = null
  private changes: ModelChangeOut[] = []
  private readonly confirmedHosts = new Set<string>()
  private saves = 0

  view(user: DevUser): ModelSettingsView {
    return {
      available: true,
      unavailable_message: null,
      you_can_change: isOperator(user),
      active: this.active,
      pending: this.pending ? this.pendingFor(user, this.pending) : null,
      providers: PROVIDERS,
      changes: this.changes.slice(0, 20),
    }
  }

  connect(user: DevUser, body: unknown): Response {
    if (!isOperator(user)) return problem(403, OPERATORS_ONLY)
    if (!isRecord(body)) return invalid('a body is required')
    const providerId = body['provider_id']
    const typed = body['base_url']
    const address =
      typeof providerId === 'string'
        ? (PROVIDERS.find((p) => p.id === providerId)?.base_url ?? '')
        : typeof typed === 'string'
          ? typed
          : ''
    const key = this.keyFor(address, body)
    if (key === null) return problem(409, 'The saved key belongs to another address. Paste the key for this one.')
    const refused = addressProblem(address)
    if (refused) return json(200, refused)
    if (key.length < 20) return json(200, refusal('key_refused', KEY_REFUSED))
    return json(200, detect(address))
  }

  save(user: DevUser, body: unknown, wall: number): Response {
    if (!isOperator(user)) return problem(403, OPERATORS_ONLY)
    if (!isRecord(body)) return invalid('a body is required')
    const { style, base_url: address, model } = body
    if ((style !== 'anthropic' && style !== 'openai') || typeof address !== 'string' || typeof model !== 'string') {
      return invalid('style, base_url and model are required')
    }
    const key = this.keyFor(address, body)
    if (key === null) return problem(409, 'The saved key belongs to another address. Paste the key for this one.')
    const refused = addressProblem(address)
    if (refused) return json(200, refused)
    const seconds = secondsFor(model)
    if (seconds > SUMMARY_WAIT_SECONDS) {
      return json(
        200,
        refusal(
          'too_slow',
          `The model answered in ${seconds} seconds. Summaries wait ${SUMMARY_WAIT_SECONDS} seconds, so runs would use the built-in sentence. Pick a faster model.`,
        ),
      )
    }
    const host = hostOf(address)
    const known = PROVIDERS.find((p) => hostOf(p.base_url) === host)
    const entry: ModelOut = {
      provider: known?.name ?? host,
      style,
      base_url: address,
      model,
      key_hint: key.slice(-2),
      test_seconds: seconds,
      by: user.id,
      by_name: user.display,
      at: new Date(wall).toISOString(),
    }
    const at = entry.at
    if (!known && !this.confirmedHosts.has(host)) {
      this.saves += 1
      this.pending = { entry, digest: `demo-${this.saves}` }
      this.log(at, user, `${user.display} asked to use ${model} at ${host}. An Approver must confirm the new address.`)
      return json(200, { status: 'awaiting_confirmation', seconds, text: SENTENCE })
    }
    const before = this.active
    this.active = entry
    const replaced = body['use_saved_key'] !== true
    const summary = !before
      ? `${user.display} turned on ${model} (${entry.provider}), with a key ending in ${entry.key_hint}.`
      : before.model !== model || before.base_url !== address
        ? `${user.display} switched to ${model} (${entry.provider}).`
        : replaced
          ? `${user.display} replaced the key, now ending in ${entry.key_hint}.`
          : null
    if (summary) this.log(at, user, summary)
    return json(200, { status: 'saved', seconds, text: SENTENCE })
  }

  turnOff(user: DevUser, wall: number): Response {
    if (!isOperator(user)) return problem(403, OPERATORS_ONLY)
    if (this.active) {
      this.active = null
      this.log(new Date(wall).toISOString(), user, `${user.display} turned the AI model off, and the saved key was deleted.`)
    }
    return new Response(null, { status: 204 })
  }

  decide(user: DevUser, body: unknown, wall: number): Response {
    if (!user.roles.includes('approver')) return problem(403, 'Only an Approver can confirm an address. Ask an Approver.')
    if (!isRecord(body) || (body['verdict'] !== 'confirm' && body['verdict'] !== 'decline') || typeof body['digest'] !== 'string') {
      return invalid('verdict and digest are required')
    }
    const pending = this.pending
    if (!pending) return problem(404, 'No address is waiting for confirmation')
    if (pending.entry.by === user.id) return problem(403, OWN_ADDRESS)
    if (pending.digest !== body['digest']) {
      return problem(409, 'The waiting address changed after you looked at it. Look again before deciding.')
    }
    const host = hostOf(pending.entry.base_url)
    const at = new Date(wall).toISOString()
    this.pending = null
    if (body['verdict'] === 'confirm') {
      this.confirmedHosts.add(host)
      this.active = pending.entry
      this.log(at, user, `${user.display} confirmed ${host}. Runs now use ${pending.entry.model}.`)
    } else {
      this.log(at, user, `${user.display} declined ${host}, and its key was deleted.`)
    }
    return json(200, this.view(user))
  }

  private pendingFor(user: DevUser, pending: Pending): PendingModelOut {
    const whyNot =
      pending.entry.by === user.id
        ? OWN_ADDRESS
        : user.roles.includes('approver')
          ? null
          : 'Only an Approver can confirm an address.'
    return { ...pending.entry, digest: pending.digest, you_can_decide: whyNot === null, why_not: whyNot }
  }

  // The key typed now, a stand-in for the saved one at its own host, or null when no saved key fits.
  private keyFor(address: string, body: Record<string, unknown>): string | null {
    if (body['use_saved_key'] !== true) return typeof body['api_key'] === 'string' ? body['api_key'] : ''
    const active = this.active
    if (!active || hostOf(active.base_url) !== hostOf(address)) return null
    return `saved-key-stand-in-${active.key_hint}`
  }

  private log(at: string, user: DevUser, summary: string): void {
    this.changes = [{ at, by: user.id, summary }, ...this.changes]
  }
}
