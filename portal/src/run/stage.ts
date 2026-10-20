import { connectorLabel, connectorNamedIn } from '../api/labels'
import type { BlockView } from '../api/types'
import { doorKey, type DoorKey } from './brand'
import { layoutRoom } from './layout'
import type { RoomView } from './live'
import {
  agentSeatKey,
  EMPTY_ROOM,
  floorPlanOf,
  stepSeatKey,
  type AgentRegistry,
  type AgentSeat,
  type Door,
  type ExpectedWrite,
  type RoomState,
  type SeatKey,
  type UserRef,
} from './room'

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

/** The specialists the agent blocks name, seated from slot 1 up, each once. */
function specialistsOf(blocks: readonly BlockView[], registry: AgentRegistry): AgentSeat[] {
  const seats: AgentSeat[] = []
  for (const block of blocks) {
    if (block.kind !== 'agent') continue
    const ref = registry.named(`${block.name} ${block.description}`)
    if (!ref || ref.id === registry.host.id || seats.some((seat) => seat.id === ref.id)) continue
    seats.push({ id: ref.id, display: ref.display, role: 'specialist', slot: seats.length + 1, status: 'present' })
  }
  return seats
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
  /** The seats the stage invented, drawn as outlines: the specialists, the starter and the Approver's seat. */
  readonly ghosts: ReadonlySet<SeatKey>
}

export interface StageOptions {
  /** The person who would start the run, seated as the Operator. */
  readonly starter?: UserRef
}

/**
 * The room a template implies before any run: the host seated, the specialists its agent blocks name,
 * the starter, one Approver's seat when it has an approval block, the Teams door, a read door per
 * connector the agent blocks name, and the write doors the template promises. No feed, no beat.
 */
export function stageSet(blocks: readonly BlockView[], registry: AgentRegistry, { starter }: StageOptions = {}): StageSet {
  const reads = readDoorsOf(blocks)
  const doors: Door[] = [{ side: 'teams' }, ...reads.map((key): Door => ({ side: 'read', key }))]
  const specialists = specialistsOf(blocks, registry)
  const approval = blocks.some((block) => block.kind === 'approval')
  const room: RoomState = {
    ...EMPTY_ROOM,
    agents: [{ id: registry.host.id, display: registry.host.display, role: 'host', slot: 0, status: 'present' }, ...specialists],
    starter: starter ?? null,
    approval: approval ? { id: 'stage', link: '', steps: [{ index: 0, label: 'Approver', state: { is: 'waiting' } }], teams: { is: 'not_posted' } } : null,
    doors,
  }
  const ghosts = new Set<SeatKey>(specialists.map((seat) => agentSeatKey(seat.id)))
  if (starter) ghosts.add('starter')
  if (approval) ghosts.add(stepSeatKey(0))
  const expectedWrites = expectedWritesOf(blocks)
  const words = stageWords(reads, expectedWrites)
  return {
    view: {
      room,
      frame: { beat: null, waiting: null, spedUp: false },
      layout: (width, expected = expectedWrites) => layoutRoom(floorPlanOf(room, expected), width),
      describe: () => words,
    },
    expectedWrites,
    words,
    ghosts,
  }
}
