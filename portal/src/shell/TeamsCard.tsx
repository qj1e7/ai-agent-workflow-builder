import type { MouseEvent } from 'react'
import { useNavigate } from 'react-router'
import type { AdaptiveCard, CardElement, CardOpenUrl, CardTextRun } from '../api/types'
import { buttonClassName } from '../ui/Button'
import { cx } from '../ui/cx'
import styles from './TeamsCard.module.css'

/*
 * Draws the Adaptive Card the platform posts to Teams (ADR 0036), for the practice copy. It knows
 * only the parts the platform's card uses: TextBlock, RichTextBlock with TextRun, and
 * Action.OpenUrl. Every text is drawn as text. The platform keeps its markdown-free headings in
 * TextBlocks and everything else in TextRuns, which Teams shows as written too.
 */

/** The path inside the app when the address is the app's own, so the practice copy opens it without a reload. */
export function inAppPath(url: string, origin: string): string | null {
  try {
    const parsed = new URL(url)
    return parsed.origin === origin ? `${parsed.pathname}${parsed.search}${parsed.hash}` : null
  } catch {
    return null
  }
}

function isWebAddress(url: string): boolean {
  try {
    const { protocol } = new URL(url)
    return protocol === 'https:' || protocol === 'http:'
  } catch {
    return false
  }
}

function tone(run: CardTextRun): string | undefined {
  return run.color && run.color !== 'default' ? run.color : undefined
}

function Run({ run }: { run: CardTextRun }) {
  return run.weight === 'bolder' ? <strong data-color={tone(run)}>{run.text}</strong> : <span data-color={tone(run)}>{run.text}</span>
}

function Element({ element }: { element: CardElement }) {
  switch (element.type) {
    case 'TextBlock':
      return <p className={cx(styles['block'], element.weight === 'bolder' && styles['heading'])}>{element.text}</p>
    case 'RichTextBlock':
      return (
        <p className={styles['block']}>
          {element.inlines.map((run, index) => (
            <Run key={index} run={run} />
          ))}
        </p>
      )
  }
}

function OpenUrl({ action, onOpen }: { action: CardOpenUrl; onOpen: () => void }) {
  const navigate = useNavigate()
  if (!isWebAddress(action.url)) return null
  function open(event: MouseEvent<HTMLAnchorElement>): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const path = inAppPath(action.url, window.location.origin)
    if (path === null) return
    event.preventDefault()
    onOpen()
    void navigate(path)
  }
  return (
    <a className={buttonClassName()} href={action.url} onClick={open}>
      {action.title}
    </a>
  )
}

/** The card's parts. The caller draws the frame, as Teams draws the message around a card. */
export function AdaptiveCardView({ card, onOpen }: { card: AdaptiveCard; onOpen: () => void }) {
  return (
    <>
      {card.body.map((element, index) => (
        <Element key={index} element={element} />
      ))}
      {card.actions.length > 0 ? (
        <div className={styles['actions']}>
          {card.actions.map((action, index) => (
            <OpenUrl key={index} action={action} onOpen={onOpen} />
          ))}
        </div>
      ) : null}
    </>
  )
}
