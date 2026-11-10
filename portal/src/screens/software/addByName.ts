import type { AddSoftware, FindOut, ProjectGuess } from '../../api/types'
import { addBody, checkName, checkSource, checkVersion, SOURCE_NAMES, type FormErrors, type SourceKind, type Watched } from './software'

/** The Add software form: the name first, then what the finder found, then the repository when the person picks it. */
export interface AddState {
  readonly step: 'name' | 'guess'
  readonly name: string
  /** Where the person says it is published, when they type it by hand. A match brings its own. */
  readonly kind: SourceKind
  readonly repo: string
  readonly version: string
  /** What the finder answered. Null when the person chose to type the GitHub address without asking. */
  readonly answer: FindOut | null
  readonly pick: number
  readonly change: boolean
  readonly errors: FormErrors
}

export const START: AddState = { step: 'name', name: '', kind: 'github', repo: '', version: '', answer: null, pick: -1, change: false, errors: {} }

export type AddAction =
  | { readonly type: 'typed'; readonly field: 'name' | 'repo' | 'version'; readonly value: string }
  | { readonly type: 'kind'; readonly kind: SourceKind }
  | { readonly type: 'answered'; readonly answer: FindOut }
  | { readonly type: 'change' }
  | { readonly type: 'picked'; readonly index: number }
  | { readonly type: 'refused'; readonly errors: FormErrors }
  | { readonly type: 'reset' }

export type Mode = 'single' | 'choose' | 'address'

/** What the person can do with one match: add it, see where it already is, or nothing, because the check can't read its releases. */
export type Verdict = { readonly kind: 'add' } | { readonly kind: 'listed'; readonly name: string } | { readonly kind: 'none' }

/** Where a match is published. Older answers name no kind, and those are GitHub projects. */
export const kindOf = (match: ProjectGuess): SourceKind => match.kind ?? 'github'

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
    case 'kind':
      return { ...state, kind: action.kind, errors: without(state.errors, 'repo') }
    case 'answered': {
      const only = action.answer.status === 'found' && action.answer.matches.length === 1 ? action.answer.matches[0] : undefined
      return { ...state, step: 'guess', answer: action.answer, pick: only && verdictOf(only).kind === 'add' ? 0 : -1, change: false, kind: 'github', repo: '', errors: {} }
    }
    case 'change': {
      const [only, ...others] = matchesOf(state)
      const keep = only && others.length === 0 && verdictOf(only).kind === 'add' ? only : undefined
      return { ...state, change: true, kind: keep ? kindOf(keep) : 'github', repo: keep ? keep.repo : '', errors: {} }
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

/** Why a match with no version the check counts is not added. */
export function noReleaseWords(repo: string, kind: SourceKind = 'github'): string {
  if (kind !== 'github') return `${repo} has no plain version number on ${SOURCE_NAMES[kind]}, so there is nothing to compare. It can’t be watched here.`
  return `${repo} doesn’t publish releases on GitHub, and it isn’t a Maven Central or npm package this check knows. It can’t be watched here.`
}

/** True when there is something to confirm: a typed address, or a match that can be added. */
export function canAdd(state: AddState): boolean {
  return modeOf(state) === 'address' || matchesOf(state).some((match) => verdictOf(match).kind === 'add')
}

type Ready = { readonly ok: true; readonly body: AddSoftware } | { readonly ok: false; readonly errors: FormErrors }

/** What to send to add the software, or what is wrong. The source is the one the person confirmed or typed, never a guess she did not see. */
export function readyToAdd(state: AddState, names: readonly string[], watched: readonly Watched[]): Ready {
  const name = checkName(state.name, names)
  const version = checkVersion(state.version)
  const errors: { name?: string; repo?: string; version?: string; form?: string } = {}
  if (!name.ok) errors.name = name.words
  if (!version.ok) errors.version = version.words
  let repo: string | null = null
  let kind: SourceKind = state.kind
  const matches = matchesOf(state)
  const mode = modeOf(state)
  if (mode === 'address') {
    const typed = checkSource(state.kind, state.repo, watched)
    if (typed.ok) repo = typed.value
    else errors.repo = typed.words
  } else {
    const chosen = matches[mode === 'single' ? 0 : state.pick]
    const verdict = chosen ? verdictOf(chosen) : null
    if (!chosen || verdict === null) errors.form = PICK_ONE
    else if (verdict.kind === 'listed') errors.form = alreadyWords(chosen.repo, verdict.name)
    else if (verdict.kind === 'none') errors.form = noReleaseWords(chosen.repo, kindOf(chosen))
    else {
      repo = chosen.repo
      kind = kindOf(chosen)
    }
  }
  if (!name.ok || !version.ok || repo === null) return { ok: false, errors }
  return { ok: true, body: addBody(name.value, kind, repo, version.value) }
}

/** Where the guess came from, in the words the form shows under the repository. A project the check can't read says why instead. */
export function releaseWords(match: ProjectGuess): string {
  const kind = kindOf(match)
  if (match.releases === 'none') return noReleaseWords(match.repo, kind)
  if (kind === 'github') return `Checked just now. The project is on GitHub and its newest release is ${match.newest ?? 'known'}.`
  return `Checked just now. The package is on ${SOURCE_NAMES[kind]} and its newest version is ${match.newest ?? 'known'}. Each check also looks up known vulnerabilities in the version you run.`
}

/** The source the form would save: the one chosen by hand, else the match that is picked or the only one. */
export function chosenKind(state: AddState): SourceKind {
  const mode = modeOf(state)
  if (mode === 'address') return state.kind
  const match = matchesOf(state)[mode === 'single' ? 0 : state.pick]
  return match ? kindOf(match) : 'github'
}
