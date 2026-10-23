import type { TeamsStubMessage } from '../../api/types'

export interface Channel {
  name: string
  count: number
}

export function channelsOf(messages: readonly TeamsStubMessage[]): Channel[] {
  const counts = new Map<string, number>()
  for (const message of messages) counts.set(message.channel, (counts.get(message.channel) ?? 0) + 1)
  return [...counts].map(([name, count]) => ({ name, count })).sort((a, b) => a.name.localeCompare(b.name))
}

export function chosenChannel(channels: readonly Channel[], wanted: string | null): string | null {
  return channels.find((channel) => channel.name === wanted)?.name ?? channels[0]?.name ?? null
}

export function messagesIn(messages: readonly TeamsStubMessage[], channel: string | null): TeamsStubMessage[] {
  return messages.filter((message) => message.channel === channel).sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))
}
