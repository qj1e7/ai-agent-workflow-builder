import { inTeamZone } from '../screens/workflows/times'

const hourIn = inTeamZone({ hour: 'numeric', hourCycle: 'h23' })
const dateIn = inTeamZone({ weekday: 'long', day: 'numeric', month: 'long' })

export function greeting(now: Date): string {
  const hour = Number(hourIn().format(now))
  if (hour >= 18) return 'Good evening'
  return hour >= 12 ? 'Good afternoon' : 'Good morning'
}

export function today(now: Date): string {
  return dateIn().format(now)
}
