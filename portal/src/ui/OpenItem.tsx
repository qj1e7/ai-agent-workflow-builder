import { useContext, type ReactNode } from 'react'
import { Button, ButtonLink, type ButtonVariant } from './Button'
import { Link } from './Link'
import { OpensInPanel, panelKey, sameItem, type PanelItem } from './sidePanel'

interface OpenProps {
  readonly item: PanelItem
  /** The item's page, where it opens from anywhere but the chat. */
  readonly to: string
  readonly children: ReactNode
  readonly 'aria-describedby'?: string
}

/** Opens an item in the side panel from the chat, and as its page anywhere else. While the panel shows the item, the chat hides it: a flow shows once. */
export function OpenButton({ item, to, variant = 'secondary', children, ...aria }: OpenProps & { readonly variant?: ButtonVariant }) {
  const opener = useContext(OpensInPanel)
  if (!opener) {
    return (
      <ButtonLink to={to} variant={variant} {...aria}>
        {children}
      </ButtonLink>
    )
  }
  if (sameItem(opener.shown, item)) return null
  return (
    <Button variant={variant} data-opens={panelKey(item)} onClick={(event) => opener.open(item, event.currentTarget)} {...aria}>
      {children}
    </Button>
  )
}

/** The same, drawn as a link, such as a workflow's name in its row. A name stays while its item is open, because it says what the row is. */
export function OpenLink({ item, to, className, id, state, children }: OpenProps & { readonly className?: string | undefined; readonly id?: string; readonly state?: unknown }) {
  const opener = useContext(OpensInPanel)
  if (!opener) {
    return (
      <Link id={id} to={to} state={state} className={className}>
        {children}
      </Link>
    )
  }
  return (
    <button type="button" id={id} className={className} data-opens={panelKey(item)} onClick={(event) => opener.open(item, event.currentTarget)}>
      {children}
    </button>
  )
}
