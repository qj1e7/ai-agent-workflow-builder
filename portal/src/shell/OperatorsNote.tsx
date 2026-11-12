import { usePeopleList } from '../api/settingsQueries'
import type { PersonOut } from '../api/types'

/** "Alice", "Alice or Carol", "Alice, Carol or Dave". */
export function whoOr(names: readonly string[]): string {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
}

export function operatorsNoteWords(what: string, people: readonly Pick<PersonOut, 'display' | 'operator'>[] | undefined): string {
  const operators = (people ?? []).filter((person) => person.operator).map((person) => person.display)
  const only = `Only Operators change ${what}.`
  return operators.length > 0 ? `${only} Ask ${whoOr(operators)}.` : only
}

/** The one note on a page that someone who isn't an Operator reads, naming the Operators on the People list. */
export function OperatorsNote({ what }: { what: string }) {
  return <>{operatorsNoteWords(what, usePeopleList().data)}</>
}
