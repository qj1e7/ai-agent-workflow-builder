import { pickStable } from './pickStable'

interface Tone {
  readonly bg: string
  readonly ink: string
}

const PERSON_TONES: readonly [Tone, ...Tone[]] = [
  { bg: 'var(--person-1-bg)', ink: 'var(--person-1-ink)' },
  { bg: 'var(--person-2-bg)', ink: 'var(--person-2-ink)' },
  { bg: 'var(--person-3-bg)', ink: 'var(--person-3-ink)' },
  { bg: 'var(--person-4-bg)', ink: 'var(--person-4-ink)' },
]

/** The colours of a person's initial. The same name gets the same colours on every screen. */
export function personTone(name: string): Tone {
  return pickStable(PERSON_TONES, name)
}
