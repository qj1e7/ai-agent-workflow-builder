const dayAndTimeSeconds = new Intl.DateTimeFormat('en-SG', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** Saved use cases can share a minute, so a row shows the second too. */
export function formatDayAndTimeSeconds(iso: string): string {
  return dayAndTimeSeconds.format(new Date(iso))
}
