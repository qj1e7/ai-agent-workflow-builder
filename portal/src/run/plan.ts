import { layoutRoom, type RoomLayout } from './layout'
import { floorPlanOf, type ExpectedWrite, type RoomState } from './room'

/** The layout of any frame, for a beat that animates away from the frame before it. */
export function layoutOf(room: RoomState, width: number, expectedWrites: readonly ExpectedWrite[] = []): RoomLayout {
  return layoutRoom(floorPlanOf(room, expectedWrites), width)
}
