import type { SimulationView, SimulatedCaseView } from '../../api/types'

/** The six kinds of scenario, in the glossary's words (ADR 0054). */
export const KIND_WORDS: Readonly<Record<SimulatedCaseView['kind'], string>> = {
  happy_path: 'Happy path',
  nothing_new: 'Nothing new',
  source_not_found: 'Source not found',
  timeout: 'Timeout',
  approver_says_no: 'Approver says no',
  odd_data: 'Odd data',
}

/** Code's grade, the verdict. A case no block could play is Not tried, never passed. */
export const VERDICT_WORDS: Readonly<Record<SimulatedCaseView['verdict'], string>> = { passed: 'Passed', failed: 'Failed', not_tried: 'Not tried' }

export const NOT_AVAILABLE = 'Simulation on practice systems isn’t available here.'
export const NOT_STARTED = 'It hasn’t been tried on practice systems yet.'
/** A revision that still needs a setting: a blank would fail every case, so it is tried once the person fills it. */
export const WAITING = 'It will be tried on practice systems once every setting is filled.'
/** The running state's one wording, as platform-api's refusal says it too. */
export const SIMULATING = 'Trying it on practice systems.'
export const NOT_FINISHED = 'It didn’t finish on practice systems in time, so there is no result.'
/** A pass never stands in for the real test run, so every result says what Turn on still does. */
export const STILL_TESTS = 'Turn on still runs the real test, which writes nothing.'
export const YOU_DECIDE = 'A failed case doesn’t stop Turn on. You decide.'
export const EXPECTED = 'Expected:'
export const HAPPENED = 'What happened:'
/** The explainer's sentence is help for the reader. Code's grade above it is the verdict. */
export const AI_NOTE = 'The AI’s note:'
export const NOT_TRIED_ANYWHERE = 'Not tried in any case:'

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** The result first, as ADR 0054 words it: how many cases were tried and how many passed. Null until there is one. */
export function simulationLead(simulation: SimulationView): string | null {
  if (simulation.state !== 'done') return null
  if (simulation.tried === 0) return 'No case could be tried on practice systems.'
  return `Tried ${plural(simulation.tried, 'case')} on practice systems: ${simulation.passed} passed.`
}

/** The most each case may take, from the platform's own number. */
export function caseLimitWords(seconds: number): string {
  const limit = seconds % 60 === 0 ? plural(seconds / 60, 'minute') : plural(seconds, 'second')
  return `Each case can take up to ${limit}.`
}

const ORDER: Readonly<Record<SimulatedCaseView['verdict'], number>> = { failed: 0, not_tried: 1, passed: 2 }

/** What failed first, then what was not tried, then what passed, each in the platform's order. */
export function casesInOrder(cases: readonly SimulatedCaseView[]): SimulatedCaseView[] {
  return [...cases].sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict])
}
