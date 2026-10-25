export const STATES = [
  'overview-load',
  'overview-mid-run',
  'overview-pause',
  'overview-writing',
  'overview-success',
  'overview-earlier-runs',
  'overview-pause-bob',
  'overview-approved-in-place',
  'run-mid-run',
  'run-pause',
  'run-success',
  'run-instant',
  'run-technical-details',
  'run-failure',
  'run-after-retry',
  'run-rejected',
  'builder-empty',
  'builder-no-model',
  'builder-planned',
  'builder-drafted',
  'builder-saved',
  'builder-library',
  'builder-cannot',
  'approvals-list',
  'approval-bob-open',
  'approval-alice-refused',
  'approval-carol-not-approver',
  'approval-approved',
  'teams-inbox',
  'jira-tickets',
  'settings-empty',
  'settings-connected',
  'settings-saved',
  'settings-pending-alice',
  'settings-pending-bob',
  'settings-confirmed',
  'reduced-motion-pause',
  'software-operator',
  'software-approver',
  'software-add-problems',
  'software-remove-confirm',
  'software-empty',
  'software-schedule-edit',
  'software-check-run',
  'software-after-check',
  'approval-check-bob',
  'jira-mark-done',
  'software-after-done',
] as const

export type StateName = (typeof STATES)[number]

/** Every state is recorded in each of these: light and dark, at 1440 by 900 and 390 by 844. */
export const PROJECTS = ['desktop', 'phone', 'desktop-dark', 'phone-dark'] as const
export const VIDEO = 'overview-success.webm'

/** The 1440 by 900 projects, where the fold checks apply. */
export function isDesktop(project: string): boolean {
  return project === 'desktop' || project === 'desktop-dark'
}
