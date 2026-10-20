import { formatDuration, formatTime } from '../../ui/format'

const DAY_MS = 86_400_000

export function waitedMs(clockMs: number, sinceIso: string): number {
  return Math.max(0, clockMs - Date.parse(sinceIso))
}

export function waitingWords(milliseconds: number): string {
  return `Waiting ${formatDuration(milliseconds)}`
}

const dayAndMonth = new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short' })

export function atWords(iso: string, nowMs: number): string {
  const sameStretch = Math.abs(nowMs - Date.parse(iso)) < DAY_MS
  return sameStretch ? `at ${formatTime(iso)}` : `on ${dayAndMonth.format(new Date(iso))} at ${formatTime(iso)}`
}
