export const STATES = [
  'overview-load',
  'overview-mid-run',
  'overview-pause',
  'overview-writing',
  'overview-success',
  'overview-earlier-runs',
  'run-mid-run',
  'run-pause',
  'run-success',
  'run-scrubbed-back',
  'run-technical-details',
  'run-failure',
  'run-after-retry',
  'run-rejected',
  'builder-empty',
  'builder-planned',
  'builder-saved',
  'approvals-list',
  'approval-bob-open',
  'approval-alice-refused',
  'approval-carol-not-approver',
  'approval-approved',
  'teams-inbox',
  'jira-tickets',
  'reduced-motion-pause',
] as const

export type StateName = (typeof STATES)[number]

export const PROJECTS = ['desktop', 'phone'] as const
export const VIDEO = 'overview-success.webm'
