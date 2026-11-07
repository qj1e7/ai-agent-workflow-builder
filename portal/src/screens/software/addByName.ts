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
  | { readonly type: 'typeAddress' }
  | { readonly type: 'change' }
  | { readonly type: 'picked'; readonly index: number }
  | { readonly type: 'refused'; readonly errors: FormErrors }
  | { readonly type: 'reset' }

export type Mode = 'single' | 'choose' | 'address'

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
      return { ...state, step: 'guess', answer: action.answer, pick: only && !only.already_listed ? 0 : -1, change: false, repo: '', errors: {} }
    }
    case 'typeAddress':
      return { ...state, step: 'guess', answer: null, pick: -1, change: true, errors: {} }
    case 'change': {
      const matches = matchesOf(state)
      return { ...state, change: true, repo: matches.length === 1 ? (matches[0]?.repo ?? '') : '', errors: {} }
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
    if (!chosen) errors.form = PICK_ONE
    else if (chosen.already_listed) errors.form = alreadyWords(chosen.repo, chosen.already_listed)
    else repo = chosen.repo
  }
  if (!name.ok || !version.ok || repo === null) return { ok: false, errors }
  return { ok: true, body: { name: name.value, repo, ...(version.value === null ? {} : { our_version: version.value }) } }
}

/** Where the guess came from, in the words the form shows under the repository. */
export function releaseWords(match: ProjectGuess): string {
  return match.releases === 'published'
    ? `Checked just now. The project is on GitHub and its newest release is ${match.newest ?? 'known'}.`
    : 'Checked just now. The project is on GitHub, but it has no release this check can compare yet, so a watch would find nothing to tell you.'
}
