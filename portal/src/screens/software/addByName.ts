import type { AddSoftware, FindOut, ProjectGuess } from '../../api/types'
import { checkName, checkRepo, checkVersion, type FormErrors } from './software'

/** The Add software form: the name first, then what the finder found, then the repository when the person picks it. */
export interface AddState {
  readonly step: 'name' | 'guess'
  readonly name: string
  readonly repo: string
  readonly version: string
  /** What the finder answered. Null when the person chose to type the GitHub address without asking. */
  readonly answer: FindOut | null
  readonly pick: number
  readonly change: boolean
  readonly errors: FormErrors
}

export const START: AddState = { step: 'name', name: '', repo: '', version: '', answer: null, pick: -1, change: false, errors: {} }

export type AddAction =
  | { readonly type: 'typed'; readonly field: 'name' | 'repo' | 'version'; readonly value: string }
  | { readonly type: 'answered'; readonly answer: FindOut }
  | { readonly type: 'change' }
  | { readonly type: 'picked'; readonly index: number }
  | { readonly type: 'refused'; readonly errors: FormErrors }
  | { readonly type: 'reset' }

export type Mode = 'single' | 'choose' | 'address'

/** What the person can do with one match: add it, see where it already is, or nothing, because the check can't read its releases. */
export type Verdict = { readonly kind: 'add' } | { readonly kind: 'listed'; readonly name: string } | { readonly kind: 'none' }

export function verdictOf(match: ProjectGuess): Verdict {
  if (match.already_listed) return { kind: 'listed', name: match.already_listed }
  return match.releases === 'published' ? { kind: 'add' } : { kind: 'none' }
}

export function matchesOf(state: AddState): readonly ProjectGuess[] {
  return state.answer?.status === 'found' ? state.answer.matches : []
}

/** One match to confirm, several to choose from, or the repository typed by hand. */
export function modeOf(state: AddState): Mode {
  const matches = matchesOf(state)
  if (state.change || matches.length === 0) return 'address'
  return matches.length === 1 ? 'single' : 'choose'
}

function without(errors: FormErrors, field: keyof FormErrors): FormErrors {
  return Object.fromEntries(Object.entries(errors).filter(([key]) => key !== field))
}

export function addReducer(state: AddState, action: AddAction): AddState {
  switch (action.type) {
    case 'typed':
      return { ...state, [action.field]: action.value, errors: without(state.errors, action.field) }
    case 'answered': {
      const only = action.answer.status === 'found' && action.answer.matches.length === 1 ? action.answer.matches[0] : undefined
      return { ...state, step: 'guess', answer: action.answer, pick: only && verdictOf(only).kind === 'add' ? 0 : -1, change: false, repo: '', errors: {} }
    }
    case 'change': {
      const [only, ...others] = matchesOf(state)
      return { ...state, change: true, repo: only && others.length === 0 && verdictOf(only).kind === 'add' ? only.repo : '', errors: {} }
    }
    case 'picked':
      return { ...state, pick: action.index, errors: {} }
    case 'refused':
      return { ...state, errors: action.errors }
    case 'reset':
      return START
  }
}

export const PICK_ONE = 'Choose one project first, or press None of these.'

export function alreadyWords(repo: string, name: string): string {
  return `${repo} is already on the list as ${name}.`
}

/** Why a project with no releases the check counts is not added. GitHub releases are the only place the check reads. */
export function noReleaseWords(repo: string): string {
  return `${repo} doesn’t publish releases on GitHub, which is the only place this check reads. It can’t be watched here.`
}

/** True when there is something to confirm: a typed address, or a match that can be added. */
export function canAdd(state: AddState): boolean {
  return modeOf(state) === 'address' || matchesOf(state).some((match) => verdictOf(match).kind === 'add')
}

type Ready = { readonly ok: true; readonly body: AddSoftware } | { readonly ok: false; readonly errors: FormErrors }

/** What to send to add the software, or what is wrong. The repository is the one the person confirmed or typed, never a guess she did not see. */
export function readyToAdd(state: AddState, names: readonly string[], repos: readonly string[]): Ready {
  const name = checkName(state.name, names)
  const version = checkVersion(state.version)
  const errors: { name?: string; repo?: string; version?: string; form?: string } = {}
  if (!name.ok) errors.name = name.words
  if (!version.ok) errors.version = version.words
  let repo: string | null = null
  const matches = matchesOf(state)
  const mode = modeOf(state)
  if (mode === 'address') {
    const typed = checkRepo(state.repo, repos)
    if (typed.ok) repo = typed.value
    else errors.repo = typed.words
  } else {
    const chosen = matches[mode === 'single' ? 0 : state.pick]
    const verdict = chosen ? verdictOf(chosen) : null
    if (!chosen || verdict === null) errors.form = PICK_ONE
    else if (verdict.kind === 'listed') errors.form = alreadyWords(chosen.repo, verdict.name)
    else if (verdict.kind === 'none') errors.form = noReleaseWords(chosen.repo)
    else repo = chosen.repo
  }
  if (!name.ok || !version.ok || repo === null) return { ok: false, errors }
  return { ok: true, body: { name: name.value, repo, ...(version.value === null ? {} : { our_version: version.value }) } }
}

/** Where the guess came from, in the words the form shows under the repository. A project the check can't read says why instead. */
export function releaseWords(match: ProjectGuess): string {
  if (match.releases === 'none') return noReleaseWords(match.repo)
  return `Checked just now. The project is on GitHub and its newest release is ${match.newest ?? 'known'}.`
}
