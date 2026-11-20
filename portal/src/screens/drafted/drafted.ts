import type { DraftedApprovalView, DraftedSetUpView, DraftedWorkflowView, DraftSettingView, N8nBlockView } from '../../api/types'
import { approvalPill } from '../run/approvalWords'
import type { Station, StepIcon } from '../run/runModel'
import type { StageTone } from '../run/words'

export interface PillWords {
  readonly label: string
  readonly tone: StageTone
}

/** The title while the drafter has no name for the workflow yet. */
export const DRAFTING_TITLE = 'Drafting it as an n8n workflow'

export const DRAFT_BUTTON = 'Draft it as an n8n workflow'

/** Under the draft button: what drafting does. A draft is checked, and isn’t set up until an Approver says yes. It says nothing of writes, since the card above may be a part card whose own Set up needs no Approver. */
export const DRAFT_NOTE = 'The Workflow drafter drafts it as its own n8n workflow, and the safety checker checks it. It isn’t set up until an Approver says yes.'

const DRAFTING: PillWords = { label: 'Drafting', tone: 'new' }
const DRAFT: PillWords = { label: 'Draft', tone: 'quiet' }
const IN_N8N: PillWords = { label: 'In n8n', tone: 'quiet' }

/** The one pill, in the words the same states have everywhere: the approval's own for a yes awaited, given or refused. A draft that could not be made has none. */
export function draftedPill(state: DraftedWorkflowView['state'], inN8n = false): PillWords | null {
  switch (state) {
    case 'drafting':
      return DRAFTING
    case 'draft':
      return inN8n ? IN_N8N : DRAFT
    case 'waiting':
      return approvalPill({ is: 'open', step: 0, steps: 1, approvedBy: [] }, false)
    case 'approved':
      return approvalPill({ is: 'approved', by: [], at: null }, false)
    case 'declined':
      return approvalPill({ is: 'declined', record: { by: '', approvedBy: [], reason: null }, at: null }, false)
    case 'not_drafted':
      return null
  }
}

export const draftedTitle = (view: Pick<DraftedWorkflowView, 'name' | 'state'>): string => view.name ?? (view.state === 'drafting' ? DRAFTING_TITLE : 'The n8n workflow')

export const revisionWords = (revision: number): string => `Revision ${String(revision)}`

/** An older revision's card settles into this one line, so only the newest card asks anything. */
export const settledWords = (revision: number, newest: number): string => `${revisionWords(revision)}. ${revisionWords(newest)} is below.`

export const IN_N8N_WORDS = 'Open in your own n8n space, without its keys.'
export const inN8nByWords = (name: string): string => `${name} has it open in n8n.`

/** What a draft open in n8n says at the left of its foot: how to use it for the person who opened it, and who has it for anyone else. Null when it is not open there. */
export function inN8nWords(view: Pick<DraftedWorkflowView, 'state' | 'in_n8n'>): string | null {
  const held = view.in_n8n
  if (held === null || view.state !== 'draft') return null
  return held.editor_url === null ? inN8nByWords(held.by_name) : IN_N8N_WORDS
}

/** The setting the server asks now, or null. */
export const questionOf = (view: DraftedWorkflowView): DraftSettingView | null => view.settings.find((setting) => setting.id === view.question) ?? null

export const guessesOf = (view: DraftedWorkflowView): DraftSettingView[] => view.settings.filter((setting) => setting.mark === 'guessed')

/** Needed settings that cannot be answered now, such as a write key an Operator adds later. */
export const waitingOf = (view: DraftedWorkflowView): DraftSettingView[] => view.settings.filter((setting) => setting.mark === 'needed' && setting.waits !== null)

export const typedPlaceholder = (kind: DraftSettingView['kind']): string => (kind === 'run_time' ? 'Like 7:45 or 6pm' : 'Type it here')

const ICON: Readonly<Record<N8nBlockView['kind'], StepIcon>> = {
  schedule: 'schedule',
  start: 'person',
  manual: 'person',
  error: 'read',
  read: 'read',
  agent: 'read',
  propose: 'read',
  ask: 'gate',
  write: 'write',
  tell: 'write',
  report: 'write',
  branch: 'read',
  merge: 'read',
  end: 'read',
  other: 'read',
  off: 'read',
}

/** The small step line: the blocks in the order a run meets them, with Start from the Portal left out, since it is a second way to start the same steps. */
export function stationsOf(blocks: readonly N8nBlockView[]): Station[] {
  return blocks
    .filter((block) => block.kind !== 'start')
    .map((block, index) => ({
      key: `${String(index)}:${block.name}`,
      spot: block.kind === 'ask' ? { at: 'gate' } : block.kind === 'write' ? { at: 'write' } : { at: 'agent', index },
      label: block.name,
      icon: ICON[block.kind],
      agent: null,
      state: 'todo',
      face: 'idle',
      under: null,
    }))
}

/** What the check added, or null when it added nothing. */
export function addedWords(added: number): string | null {
  if (added <= 0) return null
  return `Added ${String(added)} ${added === 1 ? 'thing' : 'things'} every workflow needs.`
}

export const flagsWords = (flags: number): string => `${String(flags)} ${flags === 1 ? 'flag' : 'flags'}.`

export const WAITING_WORDS = 'Waiting for an Approver. You can’t approve your own draft.'
export const CANCELLED_WAITING_WORDS = 'This revision cancelled the waiting approval.'

export const lowerFirst = (words: string): string => words.charAt(0).toLowerCase() + words.slice(1)

export const declinedWords = (approval: DraftedApprovalView | null): string => {
  const by = approval?.decided_by ?? null
  const why = approval?.reason ?? null
  const head = by === null ? 'Declined' : `Declined by ${by}`
  return `${head}${why === null ? '' : `: ${lowerFirst(why)}`}. Nothing was set up.`
}

export const approvedWords = (approval: DraftedApprovalView | null): string => (approval?.decided_by ? `Approved by ${approval.decided_by}.` : 'Approved.')

export type SetUpLine =
  | { readonly kind: 'setting_up'; readonly words: string }
  | { readonly kind: 'set_up'; readonly words: string; readonly useCaseId: string | null }
  | { readonly kind: 'failed'; readonly words: string }
  | { readonly kind: 'refused'; readonly words: string }

/** Where an approved draft stands, in the words the card and the approval page both use. Null before n8n was asked, which reads as setting up. */
export function setUpLine(setUp: DraftedSetUpView | null): SetUpLine {
  if (setUp === null || setUp.state === 'setting_up') return { kind: 'setting_up', words: 'Setting it up in n8n.' }
  if (setUp.state === 'set_up') return { kind: 'set_up', words: 'Set up as a draft.', useCaseId: setUp.use_case_id }
  return { kind: setUp.state, words: setUp.words ?? (setUp.state === 'failed' ? 'n8n didn’t take it.' : 'It changed since it was approved. It needs a new approval.') }
}

/** The words above the box while a change is being asked for. */
export const changingWords = (name: string, revision: number): string => `Changing “${name}”, ${lowerFirst(revisionWords(revision))}`

export const CHANGE_PLACEHOLDER = 'Say what to change, like “post at 9 instead”'
