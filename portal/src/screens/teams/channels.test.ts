import { describe, expect, it } from 'vitest'
import type { TeamsStubMessage } from '../../api/types'
import { channelsOf, chosenChannel, messagesIn } from './channels'

function message(id: string, channel: string, ts: string): TeamsStubMessage {
  return { id, ts, channel, text: id, link: `/approvals/${id}`, run_id: 'run', approval_id: id }
}

const messages = [
  message('b', 'CODESparks Ops', '2026-11-03T02:20:00Z'),
  message('a', 'CODESparks Ops', '2026-11-03T02:10:00Z'),
  message('c', 'Access review', '2026-11-03T02:15:00Z'),
]

describe('the channel list', () => {
  it('lists each channel once with how many messages it holds, by name', () => {
    expect(channelsOf(messages)).toEqual([
      { name: 'Access review', count: 1 },
      { name: 'CODESparks Ops', count: 2 },
    ])
  })

  it('is empty when there are no messages', () => {
    expect(channelsOf([])).toEqual([])
  })

  it('opens the first channel until one is chosen, and again if the chosen one vanishes', () => {
    const channels = channelsOf(messages)
    expect(chosenChannel(channels, null)).toBe('Access review')
    expect(chosenChannel(channels, 'CODESparks Ops')).toBe('CODESparks Ops')
    expect(chosenChannel(channels, 'Gone')).toBe('Access review')
    expect(chosenChannel([], 'Gone')).toBeNull()
  })
})

describe('the messages in a channel', () => {
  it('reads like a chat, oldest first, and shows only that channel', () => {
    expect(messagesIn(messages, 'CODESparks Ops').map((each) => each.id)).toEqual(['a', 'b'])
  })
})
