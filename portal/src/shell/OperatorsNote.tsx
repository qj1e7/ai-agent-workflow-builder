import { usePeopleList } from '../api/settingsQueries'
import type { PersonOut } from '../api/types'

/** "Alice", "Alice or Carol", "Alice, Carol or Dave". */
export function whoOr(names: readonly string[]): string {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
}

type People = readonly Pick<PersonOut, 'display' | 'operator'>[] | undefined

/** "Ask Alice or Carol.", naming the Operators on the People list, or nothing while the list is unknown. */
function askOperators(people: People): string {
  const operators = (people ?? []).filter((person) => person.operator).map((person) => person.display)
  return operators.length > 0 ? ` Ask ${whoOr(operators)}.` : ''
}

export function operatorsNoteWords(what: string, people: People): string {
  return `Only Operators change ${what}.${askOperators(people)}`
}

/** What the Planner says to a change asked by someone who isn't an Operator, as a whole answer or as a part’s cross (spec 5.3). */
export function operatorsSay(people: People): string {
  return `Operators set up workflows.${askOperators(people)}`
}

export function useOperatorsSay(): string {
  return operatorsSay(usePeopleList().data)
}

/** The one note on a page that someone who isn't an Operator reads, naming the Operators on the People list. */
export function OperatorsNote({ what }: { what: string }) {
  return <>{operatorsNoteWords(what, usePeopleList().data)}</>
}
