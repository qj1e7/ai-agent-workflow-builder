const dayAndSeconds = new Intl.DateTimeFormat('en-SG', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** The start time down to the second, so two runs started in the same minute still read differently. */
export function startedWords(iso: string): string {
  return dayAndSeconds.format(new Date(iso))
}
