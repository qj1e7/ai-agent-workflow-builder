import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type * as ButtonModule from './Button'

type Click = (event: { preventDefault: () => void }) => void

export const clicksByLabel = new Map<string, Click>()

/** The Button module with each drawn button's click kept by its words, for `vi.mock('…/ui/Button', …)`. */
export function recordingButtons(real: typeof ButtonModule): typeof ButtonModule {
  return {
    ...real,
    Button: (props) => {
      const button = real.Button(props) as ReactElement<{ onClick: Click }>
      clicksByLabel.set(renderToStaticMarkup(<>{props.children}</>).replace(/<[^>]*>/g, ''), button.props.onClick)
      return button
    },
  }
}

export function pressByLabel(label: string): void {
  const click = clicksByLabel.get(label)
  if (!click) throw new Error(`no ${label} button among ${[...clicksByLabel.keys()].join(', ')}`)
  click({ preventDefault: () => undefined })
}

export type Drawn = ReactElement<Record<string, unknown> & { children?: ReactNode }>
type Component = (props: never) => ReactNode

/** Every element a component drew, with the named components drawn out in place, as React would draw them. */
export function elementsOf(node: ReactNode, drawOut: readonly Component[]): Drawn[] {
  if (Array.isArray(node)) return node.flatMap((child: ReactNode) => elementsOf(child, drawOut))
  if (!isValidElement<Drawn['props']>(node)) return []
  const component = drawOut.find((one) => one === node.type)
  const inside = component ? component(node.props as never) : node.props.children
  return [node, ...elementsOf(inside, drawOut)]
}

export const wordsOf = (node: ReactNode): string => {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map((child: ReactNode) => wordsOf(child)).join('')
  return isValidElement<Drawn['props']>(node) ? wordsOf(node.props.children) : ''
}

/** The drawn `<button>` with these words, so a press goes through the Button's own guard while it is busy. */
export function buttonIn(elements: readonly Drawn[], label: string): Drawn {
  const found = elements.find((element) => element.type === 'button' && wordsOf(element.props.children) === label)
  if (!found) throw new Error(`no ${label} button among ${elements.filter((element) => element.type === 'button').map((element) => wordsOf(element.props.children)).join(', ')}`)
  return found
}

export const press = (button: Drawn) => (button.props['onClick'] as Click)({ preventDefault: () => undefined })

export const pressKey = (button: Drawn, key: string) => {
  let prevented = false
  ;(button.props['onKeyDown'] as ((event: { key: string; preventDefault: () => void }) => void) | undefined)?.({ key, preventDefault: () => (prevented = true) })
  return { prevented }
}
