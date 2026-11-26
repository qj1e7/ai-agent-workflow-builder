import { Link as RouterLink, type LinkProps } from 'react-router'
import { useChatLinkState } from './fromChat'
import { useSoftwareTarget } from './softwareLinks'

/** The router's Link. Inside the conversation it also passes FROM_CHAT, so the page it opens offers Back to the chat. A link to software goes to its page itself. */
export function Link({ state, to, ...rest }: LinkProps) {
  const own: unknown = state
  const fromChat = useChatLinkState()
  const target = useSoftwareTarget()
  return <RouterLink state={fromChat ? { ...(own as object | undefined), ...fromChat } : own} to={typeof to === 'string' ? target(to) : to} {...rest} />
}
