import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { HomeOut } from '../../api/types'
import { InChat } from '../../ui/fromChat'
import type { Page } from './AnswerCards'
import { useChat } from './ChatProvider'
import { PinnedLine } from './PinnedLine'
import { Thread } from './Thread'
import styles from './Planner.module.css'

interface ChatViewProps {
  readonly home: HomeOut
  readonly now: Date
  readonly page: Page
  /** The Planner's box, docked at the bottom. */
  readonly box: ReactNode
  readonly onNewChat: () => void
}

export const NEWEST = '#thread-h + ol > li:last-child'

/**
 * Home once the first message is sent (spec 5.1): the pinned Needs you line and New chat on top, the conversation scrolling
 * in the middle, and the box docked at the bottom. The scroll position is kept by the chat, so coming back from another page
 * finds the conversation where it was left.
 */
export function ChatView({ home, now, page, box, onNewChat }: ChatViewProps) {
  const chat = useChat()
  const scroller = useRef<HTMLDivElement>(null)
  const restored = useRef(false)
  const shownCount = useRef(chat.thread.messages.length)
  const [overflows, setOverflows] = useState(false)
  const { scroll } = chat

  useLayoutEffect(() => {
    restored.current = false
    const top = scroll.get()
    if (scroller.current) scroller.current.scrollTop = top
    // The cards under it are drawn again, so a position beyond the first draw is applied once they have their height.
    const frame = requestAnimationFrame(() => {
      if (scroller.current && Math.abs(scroller.current.scrollTop - top) > 1) scroller.current.scrollTop = top
      restored.current = true
    })
    return () => cancelAnimationFrame(frame)
  }, [scroll])

  const count = chat.thread.messages.length
  useLayoutEffect(() => {
    if (count > shownCount.current) scroller.current?.querySelector(NEWEST)?.scrollIntoView({ block: 'nearest' })
    shownCount.current = count
  }, [count])

  // The region is measured when the window or the conversation changes size, which a new message or a card opening does.
  useLayoutEffect(() => {
    const region = scroller.current
    const content = region?.firstElementChild
    if (!region || !content) return
    const measure = () => setOverflows(region.scrollHeight > region.clientHeight)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(region)
    observer.observe(content)
    return () => observer.disconnect()
  }, [])

  return (
    <InChat.Provider value>
      <div className={styles['chat']} data-chat>
        <div className={styles['chatBar']}>
          <h1 className="visually-hidden" tabIndex={-1}>
            Planner
          </h1>
          <PinnedLine home={home} now={now} />
          <div className={styles['chatNew']}>
            <button type="button" className={styles['linkButton']} onClick={onNewChat}>
              New chat
            </button>
          </div>
        </div>
        {/* While the conversation overflows, its region takes a Tab stop, so the keyboard can scroll it (axe: scrollable-region-focusable). */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
        <div ref={scroller} className={styles['chatScroll']} role="region" aria-label="Conversation" tabIndex={overflows ? 0 : undefined} onScroll={(event) => restored.current && scroll.set(event.currentTarget.scrollTop)}>
          <div className={styles['chatIn']}>
            <Thread thread={chat.thread} now={now} page={page} memory={chat.cardMemory} />
          </div>
        </div>
        <div className={styles['chatDock']}>{box}</div>
      </div>
    </InChat.Provider>
  )
}
