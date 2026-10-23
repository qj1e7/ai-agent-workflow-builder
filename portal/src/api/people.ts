import { useSession } from './context'
import { useDevUsers, useMe } from './queries'

export interface Person {
  readonly id: string
  readonly display: string
}

const IDENTITY_PROVIDER_OBJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function sentenceCase(id: string): string {
  const spaced = id.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function displayName(people: readonly Person[] | undefined, id: string): string {
  const known = people?.find((person) => person.id === id)
  if (known) return known.display
  return IDENTITY_PROVIDER_OBJECT_ID.test(id) ? 'a colleague' : sentenceCase(id)
}

export function usePeople(): readonly Person[] | undefined {
  const { kind } = useSession()
  const devUsers = useDevUsers()
  const me = useMe(kind === 'oidc')
  if (kind === 'dev') return devUsers.data
  return me.data ? [me.data] : undefined
}

export function useDisplayName(): (id: string) => string {
  const people = usePeople()
  return (id) => displayName(people, id)
}
