import { ApiError } from '../../api/client'
import { errorWords } from '../../api/errors'
import type { SessionKind } from '../../api/session'
import type {
  ConfirmationOut,
  DecideRefusal,
  KnownProviderOut,
  Me,
  ModelOut,
  ModelSettingsView,
  PeopleRefusal,
  PersonOut,
  ProblemReason,
  SettingsArea,
  SettingsChangeOut,
} from '../../api/types'

export type SettingsTab = 'model' | 'people'

export const SETTINGS_TABS: readonly { readonly id: SettingsTab; readonly label: string }[] = [
  { id: 'model', label: 'AI model' },
  { id: 'people', label: 'People and roles' },
]

export function tabFrom(param: string | null): SettingsTab {
  return param === 'people' ? 'people' : 'model'
}

export const ONLY_OPERATORS_WORDS = 'Only Operators change settings.'
export const NOT_SIGNED_IN_WORDS = 'Hasn’t signed in yet'
export const NO_KEY_IN_HISTORY_WORDS = 'The history never holds a key, only its last 2 characters.'
export const SETTINGS_OFF_WORDS =
  'AI model settings are switched off on this platform. The team that runs the platform can switch them on.'
export const CHECK_WHAT_YOU_TYPED_WORDS = 'Check what you typed, then try again.'

export const ROLE_RULES: readonly string[] = [
  'Making someone an Approver needs another Approver to confirm it.',
  'At least 2 people are Approvers, so nobody has to approve their own work.',
  'At least 1 person is an Operator, so someone can always change settings.',
]

export const peopleRefusalWords: Record<PeopleRefusal, string> = {
  not_an_operator: 'Only Operators change people and roles.',
  bad_email: 'That doesn’t look like an email address. Type their work email.',
  already_on_the_list: 'Someone with this email is already on the list.',
  no_role: 'Everyone needs at least one role.',
  own_operator_role: 'You can’t take away your own Operator role. Ask another Operator.',
  last_operator: 'At least 1 person must stay an Operator, so someone can still change settings.',
  two_approvers: 'At least 2 people must be Approvers, so nobody has to approve their own work.',
  already_an_approver: 'This person is already an Approver.',
  already_asked: 'An Approver has already been asked to confirm this person.',
  confirmation_waiting: 'An Approver is still deciding on this person’s Approver role. Ask them to say not now first.',
  yourself: 'You can’t take yourself off the list.',
}

export const decideRefusalWords: Record<DecideRefusal, string> = {
  not_an_approver: 'Only Approvers can confirm this.',
  you_asked: 'You asked for this, so another Approver must confirm it.',
  about_you: 'This is about you, so another Approver must confirm it.',
  already_decided: 'Someone already decided this. The page now shows where it stands.',
  digest_changed: 'This changed after you opened it. Look again before you decide.',
  person_removed: 'This person left the list after this was asked. An Operator can ask again.',
  asker_gone: 'The person who asked is no longer an Operator. Say not now, and an Operator can ask again.',
}

const PEOPLE_REFUSALS = new Set<string>(Object.keys(peopleRefusalWords))
const DECIDE_REFUSALS = new Set<string>(Object.keys(decideRefusalWords))

function refusalIn<T extends string>(error: unknown, known: ReadonlySet<string>): T | null {
  if (!(error instanceof ApiError)) return null
  const refusal = (error.body as { refusal?: unknown } | null)?.refusal
  return typeof refusal === 'string' && known.has(refusal) ? (refusal as T) : null
}

export function peopleRefusalOf(error: unknown): PeopleRefusal | null {
  return refusalIn<PeopleRefusal>(error, PEOPLE_REFUSALS)
}

export function decideRefusalOf(error: unknown): DecideRefusal | null {
  return refusalIn<DecideRefusal>(error, DECIDE_REFUSALS)
}

export type NotFound = 'person' | 'confirmation' | 'address'

const NOT_FOUND_WORDS: Record<NotFound, string> = {
  person: 'That person is no longer on the list. The list now shows who is on it.',
  confirmation: 'This request is no longer waiting. The page now shows where it stands.',
  address: 'No address is waiting any more. The page now shows where it stands.',
}

export const NOT_ACCEPTED_WORDS = 'The platform did not accept this. Reload the page, then try again.'

export function settingsErrorWords(error: unknown, signIn: SessionKind, missing: NotFound = 'person', who?: string): string {
  const people = peopleRefusalOf(error)
  if (people) return peopleRefusalWords[people]
  const decide = decideRefusalOf(error)
  if (decide) return decideRefusalWords[decide]
  if (!(error instanceof ApiError) || error.status === 401) return errorWords(error, signIn)
  if (error.status === 404) return missing === 'person' && who ? leftTheListWords([who]) : NOT_FOUND_WORDS[missing]
  if (error.status === 422) return CHECK_WHAT_YOU_TYPED_WORDS
  if (error.status === 503 && missing === 'address') return SETTINGS_OFF_WORDS
  const detail = (error.body as { detail?: unknown } | null)?.detail
  if ([403, 409, 502].includes(error.status) && typeof detail === 'string') return detail
  return error.status >= 500 ? errorWords(error, signIn) : NOT_ACCEPTED_WORDS
}

export function canChangeSettings(me: Me | undefined): boolean {
  return me?.roles.includes('operator') ?? false
}

export function keyHint(hint: string): string {
  return hint.slice(-2)
}

export function keyEndingWords(hint: string): string {
  return `API key ending ${keyHint(hint)}`
}

const shortDateTime = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'Asia/Singapore',
})

const shortDate = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Asia/Singapore' })

export function whenWords(at: string): string {
  return shortDateTime.format(new Date(at))
}

export function activeModelWords(active: ModelOut): string {
  return `${keyEndingWords(active.key_hint)}. Saved by ${active.by_name} on ${shortDate.format(new Date(active.at))}. It answered the test in ${secondsWords(active.test_seconds)}.`
}

export function secondsWords(seconds: number): string {
  return `${seconds.toFixed(1)} s`
}

export interface HistoryLine {
  readonly key: string
  readonly when: string
  readonly summary: string
  readonly who: string | null
}

export function historyOf(changes: readonly SettingsChangeOut[], area: SettingsArea): HistoryLine[] {
  return changes
    .filter((change) => change.area === area)
    .map((change, index) => ({
      key: `${change.at}-${index}`,
      when: whenWords(change.at),
      summary: change.summary,
      who: change.by_name && change.confirmed_by_name ? `Asked by ${change.by_name}, decided by ${change.confirmed_by_name}.` : null,
    }))
}

export type PendingApprover =
  | { readonly can: 'decide' }
  | { readonly can: 'not_now_only'; readonly words: string }
  | { readonly can: 'nothing'; readonly words: string }

export function pendingApproverFor(confirmation: ConfirmationOut | undefined, person: PersonOut, me: Me | undefined, askedByName: string): PendingApprover {
  if (confirmation?.you_can_decide) return { can: 'decide' }
  const asked = `Asked by ${askedByName}.`
  if (me && person.pending_approver?.asked_by === me.id) return { can: 'nothing', words: `Asked by you, so another Approver must confirm it.` }
  if (me && person.id === me.id) return { can: 'nothing', words: `${asked} It’s about you, so another Approver must confirm it.` }
  if (!me?.roles.includes('approver')) return { can: 'nothing', words: `${asked} Waiting for an Approver to confirm.` }
  const why = confirmation?.why_not
  if (why === 'asker_gone') return { can: 'not_now_only', words: decideRefusalWords.asker_gone }
  return { can: 'nothing', words: why ? `${asked} ${decideRefusalWords[why]}` : `${asked} Waiting for an Approver to confirm.` }
}

export function approverConfirmationsByPerson(confirmations: readonly ConfirmationOut[] | undefined): Map<string, ConfirmationOut> {
  return new Map((confirmations ?? []).filter((c) => c.kind === 'approver' && c.about).map((c) => [c.about?.id ?? '', c]))
}

export function needsYou(confirmations: readonly ConfirmationOut[] | undefined, kind: ConfirmationOut['kind']): boolean {
  return (confirmations ?? []).some((c) => c.kind === kind && c.you_can_decide)
}

export function modelNeedsYou(view: ModelSettingsView | undefined, me: Me | undefined): boolean {
  if (!view?.available) return false
  if (view.pending) return view.pending.you_can_decide
  return view.active === null && canChangeSettings(me)
}

export interface PeopleNotice {
  readonly personId: string
  readonly words: string
  readonly undo: { readonly name: string; readonly operator: boolean } | null
}

export interface PeopleProblem {
  readonly personId: string
  readonly words: string
}

export interface PeopleSaid {
  readonly notice: PeopleNotice | null
  readonly problem: PeopleProblem | null
  /** Who someone else took off the list, said beside the notice or the problem. */
  readonly left: string | null
}

export function leftTheListWords(names: readonly string[]): string {
  const last = names.at(-1) ?? 'That person'
  const who = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${last} are` : `${last} is`
  return `${who} no longer on the list. The list now shows who is on it.`
}

/**
 * A refusal or a fresh notice about someone still on the list stays, and the page says who left as well. What was said
 * on a row that left goes with that row: its Undo can't work, and the left-the-list line names them instead.
 */
export function saidAfterListChange(before: readonly Pick<PersonOut, 'id' | 'display'>[], after: readonly Pick<PersonOut, 'id'>[], said: PeopleSaid): PeopleSaid {
  const still = new Set(after.map((person) => person.id))
  const left = before.filter((person) => !still.has(person.id))
  if (left.length === 0) return said
  const leftIds = new Set(left.map((person) => person.id))
  const onLeftRow = (what: { readonly personId: string } | null) => what !== null && leftIds.has(what.personId)
  return {
    notice: onLeftRow(said.notice) ? null : said.notice,
    problem: onLeftRow(said.problem) ? null : said.problem,
    left: leftTheListWords(left.map((person) => person.display)),
  }
}

export function personStatusWords(person: PersonOut): string | null {
  return person.signed_in ? null : NOT_SIGNED_IN_WORDS
}

export const OTHER_ADDRESS = 'other'
export type ProviderChoice = KnownProviderOut['id'] | typeof OTHER_ADDRESS

export function hostOf(url: string): string | null {
  try {
    return new URL(url.trim()).host.toLowerCase() || null
  } catch {
    return null
  }
}

export function savedKeyFits(active: ModelOut | null, address: string): boolean {
  return active !== null && hostOf(address) !== null && hostOf(address) === hostOf(active.base_url)
}

export function startingProvider(providers: readonly KnownProviderOut[], active: ModelOut | null): ProviderChoice {
  const known = providers.find((provider) => active !== null && provider.base_url === active.base_url)
  if (known) return known.id
  if (active) return OTHER_ADDRESS
  return providers[0]?.id ?? OTHER_ADDRESS
}

export type ModelField = 'address' | 'key' | 'model' | 'form'

export function fieldOfProblem(reason: ProblemReason, step: 'key' | 'pick', other: boolean): ModelField {
  if (step === 'pick') return 'model'
  if (reason === 'key_refused') return 'key'
  if (other && (reason === 'address_not_allowed' || reason === 'unreachable' || reason === 'not_a_model_api')) return 'address'
  return 'form'
}

export function operatorChangeWords(name: string, operator: boolean): string {
  return operator ? `${name} is now an Operator.` : `${name} is no longer an Operator.`
}

export function undoneWords(name: string, operator: boolean): string {
  return operator ? `Undone. ${name} is an Operator again.` : `Undone. ${name} is no longer an Operator.`
}

export function askedApproverWords(name: string): string {
  return `Another Approver must confirm ${name} as an Approver.`
}

export function approverRemovedWords(name: string): string {
  return `${name} is no longer an Approver.`
}

export function decidedApproverWords(name: string, confirmed: boolean): string {
  return confirmed ? `${name} is now an Approver.` : `You said not now, so ${name} is not an Approver.`
}

export function addedWords(name: string, approver: boolean): string {
  return approver ? `Added ${name}. Another Approver must confirm the Approver role.` : `Added ${name}. They can sign in with their NCS account.`
}
