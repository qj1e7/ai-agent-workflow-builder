import type { Grade, N8nBlockView, UseCaseView, VersionView } from '../../api/types'

/** The chat card and the workflow page say a version's grade in these words, so the two never disagree. */
export type GradeTone = 'ok' | 'err'

const PILL: Readonly<Record<Grade, readonly [string, GradeTone]>> = {
  safe: ['Safe', 'ok'],
  writes_refused: ['Writes refused', 'err'],
  needs_a_fix: ['Needs a fix', 'err'],
}

export const gradePill = (grade: Grade): { readonly label: string; readonly tone: GradeTone } => ({ label: PILL[grade][0], tone: PILL[grade][1] })

export const ADD_THE_YES_BACK = 'Add the yes back'
export const UNDO = 'Undo'
export const UNKNOWN_PUBLISHER = 'someone we don’t know'
export const UNKNOWN_PUBLISHER_STOPS = 'We don’t know who published it in n8n, so its runs stop.'
export const DELETED_IN_N8N = 'Deleted in n8n. It won’t run again. Its runs and versions are kept.'

/** What a refused write is called: the ticket when the write block is Create ticket, else its own name. */
export function writeWords(blocks: readonly Pick<N8nBlockView, 'kind' | 'name'>[] | undefined): string {
  const write = blocks?.find((block) => block.kind === 'write')
  if (!write) return 'the write'
  if (/^create tickets?$/i.test(write.name.trim())) return /tickets$/i.test(write.name.trim()) ? 'the tickets' : 'the ticket'
  return `“${write.name}”`
}

/** The workflow page's banner for a version whose writes are refused, as the sketch says it. */
export const refusedBanner = (blocks: readonly Pick<N8nBlockView, 'kind' | 'name'>[] | undefined): string => `Writes refused: there’s no yes before ${writeWords(blocks)}.`

export const needsFixBanner = (findings: readonly string[]): string => `Needs a fix: ${findings[0] ?? 'it can’t run as the platform expects.'}`

/** The card's line under a refused write. It says "the ticket" only when a change names one. */
export function refusedLine(changes: readonly string[]): string {
  const ticket = changes.some((change) => /ticket/i.test(change))
  return `Without a yes, our platform refuses the write. The next run stops before ${ticket ? 'the ticket' : 'the write'}.`
}

/** The state pill's words on the workflow page, whenever the version in use is not safe. */
export const needsFix = (useCase: Pick<UseCaseView, 'grade'>): boolean => useCase.grade !== undefined && useCase.grade !== null && useCase.grade !== 'safe'

export const backToVersionToast = (version: number, saved: number): string => `Back to version ${version}, saved as version ${saved}.`
export const yesBackToast = (saved: number): string => `Version ${saved} has the yes back.`

/** What a version made in n8n or by a roll back says it was, or null for a version the schedule changes made. */
export function madeWords(version: Pick<VersionView, 'made' | 'changes' | 'rolled_back_to'>): string | null {
  switch (version.made) {
    case 'published_in_n8n':
      return ['Changed in n8n.', ...(version.changes ?? [])].join(' ')
    case 'rolled_back':
      return version.rolled_back_to === null || version.rolled_back_to === undefined ? 'Rolled back' : `Rolled back to version ${version.rolled_back_to}`
    case 'yes_put_back':
      return 'Put “Ask for a yes” back'
    default:
      return null
  }
}
