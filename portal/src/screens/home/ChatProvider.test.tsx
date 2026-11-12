import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { PlannerReply } from '../../api/types'
import { EMPTY_FORM } from './card'
import { ChatProvider, useChat, type Chat } from './ChatProvider'
import { desksReducer, type Desks } from './chatState'

const REPLY: PlannerReply = { answer: 'abilities' }
const ALICES = desksReducer(
  desksReducer({}, { user: 'alice', action: { type: 'sent', text: 'Check my workflows' } }),
  { user: 'alice', action: { type: 'answered', reply: REPLY, typed: 'Check my workflows' } },
)

function Probe() {
  const chat = useChat()
  return <p>{chat.thread.messages.map((message) => (message.kind === 'me' ? `me:${message.text}` : message.kind)).join(',') || 'empty'}</p>
}

function draw(signedInAs: string, initial: Desks): string {
  const session = createDevSession({ getItem: () => signedInAs, setItem: () => undefined })
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <ChatProvider initial={initial}>
          <Probe />
        </ChatProvider>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

function Grab({ onChat }: { onChat: (chat: Chat) => void }) {
  onChat(useChat())
  return null
}

function chatOf(signedInAs: string): Chat {
  const session = createDevSession({ getItem: () => signedInAs, setItem: () => undefined })
  const drawn: Chat[] = []
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <ChatProvider initial={ALICES}>
          <Grab onChat={(chat) => drawn.push(chat)} />
        </ChatProvider>
      </ApiProvider>
    </QueryClientProvider>,
  )
  const [chat] = drawn
  if (chat === undefined) throw new Error('the chat was not drawn')
  return chat
}

describe('a card’s memory in the chat', () => {
  const KEPT = { form: { ...EMPTY_FORM, name: 'Weekly check' }, draft: 'drf-1', phase: { kind: 'open' } } as const

  it('hands a card drawn again what it kept, from the same memory every time it is drawn', () => {
    const chat = chatOf('alice')
    const memory = chat.cardMemory(2)
    expect(memory.kept()).toBeUndefined()
    memory.keep(KEPT)
    expect(chat.cardMemory(2)).toBe(memory)
    expect(chat.cardMemory(2).kept()).toEqual(KEPT)
  })

  it('keeps each message’s card apart', () => {
    const chat = chatOf('alice')
    chat.cardMemory(2).keep(KEPT)
    expect(chat.cardMemory(4).kept()).toBeUndefined()
  })
})

describe('the chat above the routes', () => {
  it('gives a person the conversation they left, to whichever page reads it', () => {
    expect(draw('alice', ALICES)).toContain('me:Check my workflows,reply')
  })

  it('shows another person an empty chat, and never the last person’s (ROLE-own-chat)', () => {
    expect(draw('bob', ALICES)).toContain('empty')
    expect(draw('bob', ALICES)).not.toContain('Check my workflows')
  })

  it('starts empty when nothing was kept, which is every reload', () => {
    expect(draw('alice', {})).toContain('empty')
  })

  it('asks for its provider instead of making a second, separate chat', () => {
    const session = createDevSession({ getItem: () => 'alice', setItem: () => undefined })
    const bare = () =>
      renderToStaticMarkup(
        <QueryClientProvider client={new QueryClient()}>
          <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
            <Probe />
          </ApiProvider>
        </QueryClientProvider>,
      )
    expect(bare).toThrow('ChatProvider is missing')
  })
})
