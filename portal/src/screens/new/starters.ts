export const NEW_WORKFLOW_PATH = '/new'

export const draftPath = (draftId: string) => `${NEW_WORKFLOW_PATH}?draft=${encodeURIComponent(draftId)}`

export const FOLLOW_UP_TASK =
  'Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
const WEEKLY_SUMMARY_TASK = 'Every Friday at 4pm, find the tickets in MOCK closed this week and create one ticket that sums them up'
const KUBERNETES_TASK = 'Every Monday, check Kubernetes for new releases and raise a Jira ticket if we are behind.'

export type Starter = { readonly name: string; readonly what: string } & ({ readonly kind: 'task'; readonly task: string } | { readonly kind: 'software' })

export const FIRST_STARTERS: readonly Starter[] = [
  {
    name: 'Keep our software up to date',
    what: 'Add the software your team runs. The Software watchlist checks each one for new releases, with one approval for all the upgrade tickets.',
    kind: 'software',
  },
  { name: 'Weekly summary of closed tickets', what: 'Sum up the Jira tickets closed this week in one new ticket for the team.', kind: 'task', task: WEEKLY_SUMMARY_TASK },
  { name: 'Follow up stale bug tickets', what: 'Find bug tickets with no update for 10 days and list them in one follow-up ticket.', kind: 'task', task: FOLLOW_UP_TASK },
]

export const TASK_CHIPS: readonly { readonly name: string; readonly task: string }[] = [
  { name: 'Follow up stale bug tickets', task: FOLLOW_UP_TASK },
  { name: 'Weekly summary of closed tickets', task: WEEKLY_SUMMARY_TASK },
  { name: 'Check Kubernetes releases', task: KUBERNETES_TASK },
]

export function taskHandedOver(state: unknown): string {
  const task = (state as { task?: unknown } | null)?.task
  return typeof task === 'string' ? task : ''
}

export const draftGone = (state: unknown): boolean => (state as { draftGone?: unknown } | null)?.draftGone === true
