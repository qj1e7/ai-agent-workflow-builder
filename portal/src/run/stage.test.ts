import { describe, expect, it } from 'vitest'
import type { BlockView } from '../api/types'
import type { RoomView } from './live'
import type { ExpectedWrite } from './room'
import { stageSet } from './stage'
import { TEST_REGISTRY } from './testing'

const RELEASE_CHECK: readonly BlockView[] = [
  { key: 'read_releases', name: 'Read GitHub releases', description: '', kind: 'agent' },
  { key: 'approval_gate', name: 'Approval gate', description: '', kind: 'approval' },
  { key: 'create_ticket', name: 'Create Jira ticket', description: '', kind: 'write_action' },
]

const doorsDrawn = (view: RoomView, expected?: readonly ExpectedWrite[]) =>
  view.layout(900, expected).doors.map((door) => ({ side: door.side, key: door.key, label: door.label }))

describe('stageSet', () => {
  it('seats the host alone, present, in the centre seat', () => {
    const { view } = stageSet(RELEASE_CHECK, TEST_REGISTRY)
    expect(view.room.agents).toEqual([{ id: 'room_lead', display: 'Room lead', role: 'host', slot: 0, status: 'present' }])
    expect(view.room.phase).toEqual({ name: 'empty' })
    expect(view.room.starter).toBeNull()
    expect(view.room.ticket).toBeNull()
    expect(view.room.light).toBeNull()
    expect(view.frame).toEqual({ beat: null, waiting: null, spedUp: false })
  })

  it('draws the Teams door, the GitHub read door and the seeded Jira write door', () => {
    const { view } = stageSet(RELEASE_CHECK, TEST_REGISTRY)
    expect(doorsDrawn(view)).toEqual([
      { side: 'teams', key: 'teams', label: null },
      { side: 'read', key: 'github', label: null },
      { side: 'write', key: 'jira', label: 'Create Jira ticket' },
    ])
  })

  it('lays the room out with the write doors it was set with unless the caller passes others', () => {
    const { view, expectedWrites } = stageSet(RELEASE_CHECK, TEST_REGISTRY)
    expect(expectedWrites).toEqual([{ label: 'Create Jira ticket', key: 'jira' }])
    expect(doorsDrawn(view, [])).toEqual([
      { side: 'teams', key: 'teams', label: null },
      { side: 'read', key: 'github', label: null },
    ])
  })

  it('says what is read only and what stays locked, for the caption and the screen reader', () => {
    const { view, words } = stageSet(RELEASE_CHECK, TEST_REGISTRY)
    expect(words).toBe('The room is set. GitHub is read only. Jira stays locked until an Approver says yes.')
    expect(view.describe()).toBe(words)
  })

  it('has only the Teams door and the write door when no agent block names a connector', () => {
    const blocks: readonly BlockView[] = [
      { key: 'count', name: 'Count the open tickets', description: '', kind: 'agent' },
      { key: 'approval_gate', name: 'Approval gate', description: '', kind: 'approval' },
      { key: 'create_ticket', name: 'Create Jira ticket', description: '', kind: 'write_action' },
    ]
    const { view, words } = stageSet(blocks, TEST_REGISTRY)
    expect(doorsDrawn(view)).toEqual([
      { side: 'teams', key: 'teams', label: null },
      { side: 'write', key: 'jira', label: 'Create Jira ticket' },
    ])
    expect(words).toBe('The room is set. Jira stays locked until an Approver says yes.')
  })

  it('names each read door once and joins names with and', () => {
    const blocks: readonly BlockView[] = [
      { key: 'a', name: 'Read GitHub releases', description: '', kind: 'agent' },
      { key: 'b', name: 'Read GitHub issues', description: '', kind: 'agent' },
      { key: 'c', name: 'Read the GitLab inventory', description: '', kind: 'agent' },
      { key: 'd', name: 'Update the Confluence page', description: '', kind: 'write_action' },
      { key: 'e', name: 'Create Jira ticket', description: '', kind: 'write_action' },
    ]
    const { view, words } = stageSet(blocks, TEST_REGISTRY)
    expect(doorsDrawn(view).filter((door) => door.side === 'read').map((door) => door.key)).toEqual(['github', 'gitlab'])
    expect(words).toBe('The room is set. GitHub and GitLab are read only. Confluence and Jira stay locked until an Approver says yes.')
  })

  it('says nothing can be written when the template has no write block', () => {
    const blocks: readonly BlockView[] = [{ key: 'read_releases', name: 'Read GitHub releases', description: '', kind: 'agent' }]
    const { view, expectedWrites, words } = stageSet(blocks, TEST_REGISTRY)
    expect(expectedWrites).toEqual([])
    expect(doorsDrawn(view).map((door) => door.side)).toEqual(['teams', 'read'])
    expect(words).toBe('The room is set. GitHub is read only. Nothing can be written without an Approver.')
  })
})
