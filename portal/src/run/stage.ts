import { connectorLabel, connectorNamedIn } from '../api/labels'
import type { BlockView } from '../api/types'
import { doorKey, type DoorKey } from './brand'
import { layoutRoom } from './layout'
import type { RoomView } from './live'
import { EMPTY_ROOM, floorPlanOf, type AgentRegistry, type Door, type ExpectedWrite, type RoomState } from './room'

export function expectedWritesOf(blocks: readonly BlockView[] | undefined): ExpectedWrite[] {
  return (blocks ?? [])
    .filter((block) => block.kind === 'write_action')
    .map((block) => {
      const connector = connectorNamedIn(block.name)
      return { label: block.name, key: connector ? doorKey(connector) : null }
    })
}

function readDoorsOf(blocks: readonly BlockView[]): DoorKey[] {
  const keys: DoorKey[] = []
  for (const block of blocks) {
    if (block.kind !== 'agent') continue
    const connector = connectorNamedIn(block.name)
    if (!connector) continue
    const key = doorKey(connector)
    if (!keys.includes(key)) keys.push(key)
  }
  return keys
}

function stageWords(reads: readonly DoorKey[], writes: readonly ExpectedWrite[]): string {
  const sentences = ['The room is set.']
  if (reads.length > 0) {
    sentences.push(`${reads.map(connectorLabel).join(' and ')} ${reads.length === 1 ? 'is' : 'are'} read only.`)
  }
  if (writes.length > 0) {
    const names = writes.map((write) => (write.key ? connectorLabel(write.key) : write.label))
    sentences.push(`${names.join(' and ')} ${writes.length === 1 ? 'stays' : 'stay'} locked until an Approver says yes.`)
  } else {
    sentences.push('Nothing can be written without an Approver.')
  }
  return sentences.join(' ')
}

export interface StageSet {
  readonly view: RoomView
  readonly expectedWrites: readonly ExpectedWrite[]
  /** One plain sentence for the caption and the screen reader: what is set and what stays locked. */
  readonly words: string
}

/**
 * The room a template implies before any run: the host seated, the Teams door, a read door per
 * connector the agent blocks name, and the write doors the template promises. No feed, no beat.
 */
export function stageSet(blocks: readonly BlockView[], registry: AgentRegistry): StageSet {
  const reads = readDoorsOf(blocks)
  const doors: Door[] = [{ side: 'teams' }, ...reads.map((key): Door => ({ side: 'read', key }))]
  const room: RoomState = {
    ...EMPTY_ROOM,
    agents: [{ id: registry.host.id, display: registry.host.display, role: 'host', slot: 0, status: 'present' }],
    doors,
  }
  const expectedWrites = expectedWritesOf(blocks)
  const words = stageWords(reads, expectedWrites)
  return {
    view: {
      room,
      frame: { beat: null, waiting: null },
      layout: (width, expected = expectedWrites) => layoutRoom(floorPlanOf(room, expected), width),
      describe: () => words,
    },
    expectedWrites,
    words,
  }
}
