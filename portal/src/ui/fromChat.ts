import { createContext, useContext } from 'react'
import { useLocation } from 'react-router'

/** Passed as a link's state when it leaves the chat, so the page it opens offers Back to the chat in place of its own Back. */
export const FROM_CHAT = { fromChat: true }

export function openedFromChat(state: unknown): boolean {
  return typeof state === 'object' && state !== null && 'fromChat' in state
}

export function useFromChat(): boolean {
  return openedFromChat(useLocation().state)
}

/** True inside the conversation, where every button that opens a page passes FROM_CHAT. */
export const InChat = createContext(false)

export function useChatLinkState(): typeof FROM_CHAT | undefined {
  return useContext(InChat) ? FROM_CHAT : undefined
}
