export interface DurationOptions {
  /** Drop the seconds once the duration is a minute or more. */
  readonly coarse?: boolean
  /** Join the numbers and units with non-breaking spaces, so a counter breaks only before the duration. */
  readonly noWrap?: boolean
}

export function formatDuration(milliseconds: number, { coarse = false, noWrap = false }: DurationOptions = {}): string {
  const total = Math.max(0, Math.floor(milliseconds / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const parts: string[] = []
  if (hours > 0) {
    parts.push(`${hours} h`)
    if (minutes > 0) parts.push(`${minutes} min`)
  } else if (minutes > 0) {
    parts.push(`${minutes} min`)
    if (!coarse) parts.push(`${seconds} s`)
  } else {
    parts.push(`${seconds} s`)
  }
  const words = parts.join(' ')
  return noWrap ? words.replaceAll(' ', '\u00a0') : words
}

export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = String(total % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`
}

const timeOfDay = new Intl.DateTimeFormat('en-SG', { hour: '2-digit', minute: '2-digit', hour12: false })
const dayAndTime = new Intl.DateTimeFormat('en-SG', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

const dayOnly = new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short' })

export function formatDay(iso: string): string {
  return dayOnly.format(new Date(iso))
}

export function formatTime(iso: string): string {
  return timeOfDay.format(new Date(iso))
}

export function formatDayAndTime(iso: string): string {
  return dayAndTime.format(new Date(iso))
}

export function formatRelative(iso: string, nowMs: number): string {
  const seconds = Math.round((nowMs - Date.parse(iso)) / 1000)
  if (seconds < 45) return 'Just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'Yesterday' : `${days} days ago`
}

const SHORT_DIGEST_HEAD = 'sha256:'.length + 4

export function shortDigest(digest: string): string {
  return digest.length <= SHORT_DIGEST_HEAD + 5 ? digest : `${digest.slice(0, SHORT_DIGEST_HEAD)}…${digest.slice(-4)}`
}
