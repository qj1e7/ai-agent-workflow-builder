import { connectorLabel, operationLabel } from '../../api/labels'
import type { WriteActionView } from '../../api/types'

export interface ActionRow {
  label: string
  value: string
}

export interface ActionDescription {
  rows: ActionRow[]
  title: string | null
  body: string | null
}

function sentenceCase(key: string): string {
  const spaced = key.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function show(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function textOf(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

export function describeAction(action: WriteActionView): ActionDescription {
  const { title, body, ...otherFields } = action.fields
  const rows: ActionRow[] = [
    { label: 'System', value: connectorLabel(action.connector) },
    { label: 'Action', value: operationLabel(action.operation) },
    ...Object.entries(action.target).map(([key, value]) => ({ label: sentenceCase(key), value: show(value) })),
    ...Object.entries(otherFields).map(([key, value]) => ({ label: sentenceCase(key), value: show(value) })),
  ]
  return { rows, title: textOf(title), body: textOf(body) }
}

export function systemsWritten(actions: readonly WriteActionView[]): string {
  const names = [...new Set(actions.map((action) => connectorLabel(action.connector)))]
  if (names.length === 0) return 'the system'
  return names.length === 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names.at(-1) ?? ''}`
}

/** The approval page's title: "Approve a write to Jira", or "Approve 3 writes to Jira" for a check with several tickets. */
export function approvalTitle(actions: readonly WriteActionView[]): string {
  const systems = systemsWritten(actions)
  return actions.length > 1 ? `Approve ${actions.length} writes to ${systems}` : `Approve a write to ${systems === 'the system' ? 'Jira' : systems}`
}
