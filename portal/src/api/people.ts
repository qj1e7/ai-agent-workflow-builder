import { useDevUsers } from './queries'
import type { DevUser } from './types'

function sentenceCase(id: string): string {
  const spaced = id.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function displayName(users: readonly DevUser[] | undefined, id: string): string {
  return users?.find((user) => user.id === id)?.display ?? sentenceCase(id)
}

export function useDisplayName(): (id: string) => string {
  const { data } = useDevUsers()
  return (id) => displayName(data, id)
}
