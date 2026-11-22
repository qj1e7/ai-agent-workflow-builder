import type { ReactElement } from 'react'
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
