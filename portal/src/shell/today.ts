const TIME_ZONE = 'Asia/Singapore'

const hourIn = new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone: TIME_ZONE })
const dateIn = new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', timeZone: TIME_ZONE })

export function greeting(now: Date): string {
  const hour = Number(hourIn.format(now))
  if (hour >= 18) return 'Good evening'
  return hour >= 12 ? 'Good afternoon' : 'Good morning'
}

/** For example "Thursday 29 October". */
export function today(now: Date): string {
  return dateIn.format(now)
}
