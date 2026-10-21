import { describe, expect, it } from 'vitest'
import { agentId } from './brand'
import { describeRoom } from './describe'
import { slice } from './recordings'
import { applyEvent, EMPTY_ROOM, type RoomState } from './room'
import { TEST_REGISTRY } from './testing'

function foldSuccess(to: number): RoomState {
  return slice('success', 1, to).reduce((room, event) => applyEvent(room, event, TEST_REGISTRY).room, EMPTY_ROOM)
}

describe('describeRoom', () => {
  it('says what lies on the table and which door it came through, until the proposal takes the table', () => {
    expect(describeRoom(foldSuccess(9), null)).toContain('On the table: 1.2.16, 1.2.15, from GitHub.')
    expect(describeRoom(foldSuccess(7), null)).not.toContain('On the table')
    expect(describeRoom(foldSuccess(12), null)).not.toContain('On the table')
  })

  it('leaves the door out when the step had no trip', () => {
    const room: RoomState = { ...foldSuccess(9), finding: { agent: agentId('room_lead'), step: 'count', from: null, items: ['3 open', '1 closed'] } }
    expect(describeRoom(room, null)).toContain('On the table: 3 open, 1 closed.')
  })
})
