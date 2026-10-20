export function formatDuration(milliseconds: number): string {
  const total = Math.max(0, Math.floor(milliseconds / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`
  if (minutes > 0) return `${minutes} min ${seconds} s`
  return `${seconds} s`
}

export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

const timeOfDay = new Intl.DateTimeFormat('en-SG', { hour: '2-digit', minute: '2-digit', hour12: false })
const dayAndTime = new Intl.DateTimeFormat('en-SG', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

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
