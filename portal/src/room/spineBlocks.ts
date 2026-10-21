import type { BlockView } from '../api/types'
import type { LiveView, Station } from '../run'
import { formatDuration } from '../ui/format'
import type { SpineBlock } from '../ui/Spine'
import type { SpineState } from '../ui/spineState'

function stateOf(station: Station, frame: LiveView['frame']): SpineState {
  const state = station.state
  switch (state.is) {
    case 'waiting':
      // The frame's wait is the seat's number; a station waiting on another step counts from scene time.
      return { kind: 'waiting', waited: formatDuration(frame.waiting?.since === state.since ? frame.waiting.elapsedMs : Math.max(0, frame.sceneTime - state.since)) }
    case 'approved':
      return { kind: 'approved', by: state.by.map((user) => user.display).join(' and ') }
    case 'declined':
      return { kind: 'declined', by: state.by.display }
    default:
      return { kind: state.is }
  }
}

/** The use case's blocks as spine stations, with the live view's words for each. */
export function spineBlocks(view: LiveView, blocks: readonly BlockView[] | undefined): SpineBlock[] {
  if (!blocks) return []
  return view.spine(blocks).map((station) => ({
    key: station.block.key,
    name: station.block.name,
    kind: station.block.kind,
    state: stateOf(station, view.frame),
    description: station.block.description,
  }))
}
