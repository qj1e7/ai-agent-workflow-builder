import type { SoftwareStatus, VersionSourceView, WatchedSoftwareView, WatchlistView } from '../../api/types'
import { formatDay } from '../../ui/format'
import type { PillTone } from '../../ui/StatusPill'

/** What one row of the Software page shows. */
export interface SoftwareRow {
  readonly id: string
  readonly name: string
  readonly source: { readonly ref: string; readonly url: string }
  /** Null until the first check takes the newest release as ours. */
  readonly ours: string | null
  /** Where our version came from, in a few words. */
  readonly oursFrom: string
  readonly newest: string | null
  readonly status: SoftwareStatus
  readonly label: string
  readonly tone: PillTone
  /** The sentence the check gave when it could not read the source. */
  readonly problem: string | null
  /** What resolves the row, when the row itself can lead there. */
  readonly next: RowNext | null
}

export type RowNext = { readonly is: 'approval'; readonly to: string } | { readonly is: 'ticket'; readonly key: string }

/** The page's two parts: rows that need a person, in the platform's order, and the rows folded under "N up to date". */
export interface SoftwareList {
  readonly attention: readonly SoftwareRow[]
  readonly upToDate: readonly SoftwareRow[]
}

export const STATUS: Readonly<Record<SoftwareStatus, { readonly label: string; readonly tone: PillTone }>> = {
  cant_check: { label: "Can't check", tone: 'failed' },
  behind: { label: 'Behind', tone: 'waiting' },
  awaiting_approval: { label: 'Waiting for approval', tone: 'waiting' },
  ticket_open: { label: 'Ticket open', tone: 'working' },
  not_checked: { label: 'Not checked yet', tone: 'neutral' },
  up_to_date: { label: 'Up to date', tone: 'done' },
}

export const NOT_SET = 'Set at the first check'

export function oursFrom(source: VersionSourceView | null): string {
  if (source === null) return NOT_SET
  switch (source.kind) {
    case 'given':
      return 'Given when added'
    case 'first_check':
      return 'Newest at the first check'
    case 'ticket_done':
      return source.ticket ? `From ${source.ticket}, Done ${formatDay(source.at)}` : `Done ${formatDay(source.at)}`
  }
}

function nextOf(software: WatchedSoftwareView): RowNext | null {
  if (software.status === 'awaiting_approval' && software.approval_id) {
    return { is: 'approval', to: `/approvals/${software.approval_id}` }
  }
  if (software.status === 'ticket_open' && software.open_ticket) return { is: 'ticket', key: software.open_ticket }
  return null
}

export function rowOf(software: WatchedSoftwareView): SoftwareRow {
  const look = STATUS[software.status]
  return {
    id: software.id,
    name: software.name,
    source: { ref: software.source.ref, url: software.source.url },
    ours: software.our_version,
    oursFrom: software.our_version === null ? NOT_SET : oursFrom(software.our_version_source),
    newest: software.newest_version,
    status: software.status,
    label: look.label,
    tone: look.tone,
    problem: software.status === 'cant_check' ? software.problem : null,
    next: nextOf(software),
  }
}

/** The platform already sends the rows attention first, so the order is kept and only the up to date rows are split off. */
export function softwareList(view: WatchlistView | null): SoftwareList {
  const rows = (view?.software ?? []).map(rowOf)
  return {
    attention: rows.filter((row) => row.status !== 'up_to_date'),
    upToDate: rows.filter((row) => row.status === 'up_to_date'),
  }
}

export function upToDateWords(count: number): string {
  return `${count} up to date`
}
