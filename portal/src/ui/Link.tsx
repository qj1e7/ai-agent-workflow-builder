import { Link as RouterLink, type LinkProps } from 'react-router'
import { useChatLinkState } from './fromChat'

/** The router's Link. Inside the conversation it also passes FROM_CHAT, so the page it opens offers Back to the chat. */
export function Link({ state, ...rest }: LinkProps) {
  const own: unknown = state
  const fromChat = useChatLinkState()
  return <RouterLink state={fromChat ? { ...(own as object | undefined), ...fromChat } : own} {...rest} />
}
