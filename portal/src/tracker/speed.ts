import type { Speed } from '../run'

export const SPEED_KEY = 'portal.speed'

export const SPEEDS: readonly { readonly value: Speed; readonly label: string }[] = [
  { value: 1, label: '1x' },
  { value: 2, label: '2x' },
  { value: 'instant', label: 'Instant' },
]

/** Anything but a stored '2' or 'instant' reads as 1x. */
export function parseSpeed(stored: string | null): Speed {
  return stored === '2' ? 2 : stored === 'instant' ? 'instant' : 1
}

function readStored(): Speed {
  try {
    return parseSpeed(window.localStorage.getItem(SPEED_KEY))
  } catch {
    return 1
  }
}

let current: Speed | null = null

/** The viewer's remembered speed. A new run view starts at it. */
export function getSpeed(): Speed {
  current ??= readStored()
  return current
}

export function rememberSpeed(speed: Speed): void {
  current = speed
  try {
    window.localStorage.setItem(SPEED_KEY, String(speed))
  } catch {
    // The choice still holds for this tab when storage is blocked.
  }
}
