import { ApiError } from '../../api/client'
import type { AddSoftware } from '../../api/types'

export interface AddFields {
  readonly name: string
  readonly repo: string
  readonly ourVersion: string
}

export type AddField = keyof AddFields

export type FieldProblems = Partial<Record<AddField, string>>

export type Checked =
  { readonly ok: true; readonly body: AddSoftware } | { readonly ok: false; readonly problems: FieldProblems }

export const EMPTY_FIELDS: AddFields = { name: '', repo: '', ourVersion: '' }

const NAME_LIMIT = 80
// The platform's RepoName pattern: a GitHub owner, a slash and a repository name.
export const REPO = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/
const VERSION = /^\d+\.\d+\.\d+$/
const GITHUB_ADDRESS = /^(?:https?:\/\/)?(?:www\.)?github\.com\/([^/?#\s]+)\/([^/?#\s]+)/i

export const WORDS = {
  nameMissing: "Write the software's name.",
  nameTooLong: `Keep the name to ${NAME_LIMIT} characters.`,
  repoMissing: 'Write the GitHub repository, such as langchain-ai/langgraph.',
  repoShape: 'Write it as owner/name, such as langchain-ai/langgraph.',
  version: 'Write three numbers, such as 1.2.14, or leave it empty.',
} as const

/** owner/name from what was typed, so a pasted GitHub address works too. */
export function repoFrom(typed: string): string {
  const trimmed = typed.trim()
  const address = GITHUB_ADDRESS.exec(trimmed)
  const repo = address ? `${address[1] ?? ''}/${address[2] ?? ''}` : trimmed.replace(/^\/+|\/+$/g, '')
  return repo.replace(/\.git$/i, '')
}

/** A version without the "v" that release tags often carry. */
export function versionFrom(typed: string): string {
  return typed.trim().replace(/^v(?=\d)/i, '')
}

export function checkAdd(fields: AddFields): Checked {
  const name = fields.name.trim()
  const repo = repoFrom(fields.repo)
  const version = versionFrom(fields.ourVersion)
  const problems: FieldProblems = {}
  if (name === '') problems.name = WORDS.nameMissing
  else if (name.length > NAME_LIMIT) problems.name = WORDS.nameTooLong
  if (repo === '') problems.repo = WORDS.repoMissing
  else if (!REPO.test(repo)) problems.repo = WORDS.repoShape
  if (version !== '' && !VERSION.test(version)) problems.ourVersion = WORDS.version
  if (Object.keys(problems).length > 0) return { ok: false, problems }
  return { ok: true, body: { name, repo, our_version: version === '' ? null : version } }
}

const FIELD_OF: ReadonlyMap<unknown, AddField> = new Map<unknown, AddField>([
  ['name', 'name'],
  ['repo', 'repo'],
  ['our_version', 'ourVersion'],
])
const FIELD_WORDS: Readonly<Record<AddField, string>> = {
  name: WORDS.nameMissing,
  repo: WORDS.repoShape,
  ourVersion: WORDS.version,
}

export interface Refused {
  readonly fields: FieldProblems
  /** A problem that is not about one field, such as a full watchlist. */
  readonly form: string | null
}

export function detailsOf(body: unknown): { loc: unknown[]; msg: string }[] {
  if (typeof body !== 'object' || body === null) return []
  const detail = (body as { detail?: unknown }).detail
  if (!Array.isArray(detail)) return []
  return detail.flatMap((item: unknown) => {
    if (typeof item !== 'object' || item === null) return []
    const { loc, msg } = item as { loc?: unknown; msg?: unknown }
    return Array.isArray(loc) && typeof msg === 'string' ? [{ loc, msg }] : []
  })
}

/**
 * The platform's refusal of an add, as field problems in our words: a repository already watched, or a field it
 * would not take. Null when the error is not one of these, so the page explains it the usual way.
 */
export function refusedAdd(error: unknown, body: AddSoftware): Refused | null {
  if (!(error instanceof ApiError)) return null
  if (error.status === 409) return { fields: { repo: `${body.repo} is already on the list.` }, form: null }
  if (error.status !== 422) return null
  const fields: FieldProblems = {}
  let form: string | null = null
  for (const { loc, msg } of detailsOf(error.body)) {
    const field = FIELD_OF.get(loc.at(-1))
    if (field) fields[field] = FIELD_WORDS[field]
    else form = msg.endsWith('.') ? msg : `${msg}.`
  }
  return Object.keys(fields).length > 0 || form ? { fields, form } : null
}
