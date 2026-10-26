/** Every element the tour can point at. A screen marks one with tourStop(), and the tour finds it by name. */
export const TOUR_STOPS = [
  'user-menu',
  'theme',
  'settings',
  'nav-runs',
  'nav-builder',
  'nav-software',
  'nav-approvals',
  'nav-teams',
  'nav-jira',
  'model-on',
  'plan-example',
  'plan',
  'plan-result',
  'run-details',
  'save-and-run',
  'run-status',
  'run-line',
  'speed',
  'tech-details',
  'written',
  'open-approval',
  'decision',
  'decide',
  'watch-run',
  'agent-library',
  'copy-edit',
  'card-editor',
  'remove-jira-detail',
  'add-detail',
  'card-problems',
  'card-ready',
  'save-agent',
  'schedule',
  'add-form',
  'add-software',
  'check-now',
] as const

export type TourStop = (typeof TOUR_STOPS)[number]

/** The attribute that marks an element as one or more tour stops. Spread it onto the element. */
export function tourStop(...names: readonly TourStop[]): { 'data-tour': string } {
  return { 'data-tour': names.join(' ') }
}

export function stopSelector(name: TourStop): string {
  return `[data-tour~="${name}"]`
}
