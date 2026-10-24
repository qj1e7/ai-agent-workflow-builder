import type { ConnectIn, Connected, FoundModel, KnownProviderOut, ModelOut, ModelSettingsView, SaveIn } from '../../api/types'

export const OTHER = 'other'
export type Choice = KnownProviderOut['id'] | typeof OTHER

export function hostOf(address: string): string {
  try {
    return new URL(address.trim()).hostname.toLowerCase()
  } catch {
    return ''
  }
}

export function addressFor(choice: Choice, providers: readonly KnownProviderOut[], typed: string): string {
  if (choice === OTHER) return typed.trim()
  return providers.find((provider) => provider.id === choice)?.base_url ?? ''
}

// The platform refuses the saved key anywhere else, so the form only offers it at the same host.
export function savedKeyFits(active: ModelOut | null, address: string): boolean {
  if (!active) return false
  const host = hostOf(address)
  return host !== '' && host === hostOf(active.base_url)
}

export function suggestedModel(models: readonly FoundModel[]): string {
  return (models.find((model) => model.suggested) ?? models[0])?.id ?? ''
}

export function maskedKey(hint: string): string {
  return `•••••••••••• ${hint}`
}

function keyPart(key: string, useSavedKey: boolean): Pick<ConnectIn, 'api_key' | 'use_saved_key'> {
  return useSavedKey ? { use_saved_key: true } : { api_key: key.trim(), use_saved_key: false }
}

export function connectBody(choice: Choice, typed: string, key: string, useSavedKey: boolean): ConnectIn {
  const address = choice === OTHER ? { base_url: typed.trim() } : { provider_id: choice }
  return { ...address, ...keyPart(key, useSavedKey) }
}

// The address and style come from what Connect found, so a model is saved where it was tested.
export function saveBody(connected: Connected, model: string, key: string, useSavedKey: boolean): SaveIn {
  return { style: connected.style, base_url: connected.base_url, model, ...keyPart(key, useSavedKey) }
}

export function missingForConnect(choice: Choice, typed: string, key: string, useSavedKey: boolean): string | null {
  if (choice === OTHER && typed.trim() === '') return 'Type the address first.'
  if (!useSavedKey && key.trim() === '') return 'Paste the key first.'
  return null
}

// The form opens where the saved model lives, so changing only the model keeps the saved key.
export function startingChoice(view: ModelSettingsView): { choice: Choice; typed: string } {
  const active = view.active
  if (!active) return { choice: view.providers[0]?.id ?? OTHER, typed: '' }
  const known = view.providers.find((provider) => hostOf(provider.base_url) === hostOf(active.base_url))
  return known ? { choice: known.id, typed: '' } : { choice: OTHER, typed: active.base_url }
}

// How long a test answer took, in words. The platform rounds to a tenth, so a quick answer comes back as 0.
export function answerTime(seconds: number): string {
  if (seconds < 1) return 'under a second'
  return seconds === 1 ? '1 second' : `${seconds} seconds`
}
