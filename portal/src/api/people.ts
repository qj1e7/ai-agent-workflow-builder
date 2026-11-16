import { usePeopleList } from './settingsQueries'
import { useMe } from './queries'

export interface Person {
  readonly id: string
  readonly display: string
}

const IDENTITY_PROVIDER_OBJECT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
/** The id the People list gives each person it adds, such as per_01M7HH1YX20KNDD6FB2ERHWAZG. */
const PERSON_ID = /^per_[0-9A-Z]{26}$/
/** Names change rarely, so a page that names people reads the People list again at most once a minute. */
const NAMES_STALE_MS = 60_000

function sentenceCase(id: string): string {
  const spaced = id.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function displayName(people: readonly Person[] | undefined, id: string): string {
  const known = people?.find((person) => person.id === id)
  if (known) return known.display
  return IDENTITY_PROVIDER_OBJECT_ID.test(id) || PERSON_ID.test(id) ? 'a colleague' : sentenceCase(id)
}

/** Everyone on the People list, which every signed-in person may read, so anyone the team added is named, not only the seeded people. */
export function usePeople(): readonly Person[] | undefined {
  const people = usePeopleList({ staleTime: NAMES_STALE_MS })
  const me = useMe()
  return people.data ?? (me.data ? [me.data] : undefined)
}

export function useDisplayName(): (id: string) => string {
  const people = usePeople()
  return (id) => displayName(people, id)
}
