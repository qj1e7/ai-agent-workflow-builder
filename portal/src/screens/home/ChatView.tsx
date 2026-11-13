import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { HomeOut } from '../../api/types'
import { InChat } from '../../ui/fromChat'
import { NARROW, useMediaQuery } from '../../ui/media'
import { openerAfterClose, OpensInPanel, panelKey, type PanelItem, type PanelOpener } from '../../ui/sidePanel'
import type { Page } from './AnswerCards'
import { useChat, type OpenPanel } from './ChatProvider'
import { PinnedLine } from './PinnedLine'
import { PANEL_HEADING, SidePanel } from './SidePanel'
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

const openersOf = (root: HTMLElement | null, item: PanelItem): HTMLElement[] => [...(root?.querySelectorAll<HTMLElement>(`[data-opens="${panelKey(item)}"]`) ?? [])]

/**
 * Home once the first message is sent (spec 5.1): the pinned Needs you line and New chat on top, the conversation scrolling
 * in the middle, and the box docked at the bottom. The scroll position is kept by the chat, so coming back from another page
 * finds the conversation where it was left. An item opened from a card shows in the side panel beside it (spec 3.3).
 */
export function ChatView({ home, now, page, box, onNewChat }: ChatViewProps) {
  const chat = useChat()
  const column = useRef<HTMLDivElement>(null)
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

  // An answer takes the place of its "answering" line, so the count stays the same and the answer, often a tall card, would
  // land below the fold. It is brought into view from its top. An answer already there when the chat comes back keeps the
  // restored position.
  const newest = chat.thread.messages.at(-1)
  const answered = newest?.kind === 'reply' ? newest.id : null
  const shownAnswer = useRef(answered)
  useLayoutEffect(() => {
    if (answered === null || answered === shownAnswer.current) return
    shownAnswer.current = answered
    const region = scroller.current
    const item = region?.querySelector<HTMLElement>(NEWEST)
    if (!region || !item) return
    // Only the conversation scrolls, never the page around it.
    const show = () => {
      const view = region.getBoundingClientRect()
      const box = item.getBoundingClientRect()
      if (box.height > view.height) region.scrollTop += box.top - view.top
      else if (box.bottom > view.bottom) region.scrollTop += box.bottom - view.bottom
    }
    show()
    // A card can grow once its own data arrives, so the answer is followed for a moment, until the person scrolls.
    const observer = new ResizeObserver(show)
    observer.observe(item)
    const stop = () => observer.disconnect()
    const timer = window.setTimeout(stop, 2000)
    region.addEventListener('wheel', stop, { once: true, passive: true })
    region.addEventListener('touchstart', stop, { once: true, passive: true })
    return () => {
      stop()
      window.clearTimeout(timer)
      region.removeEventListener('wheel', stop)
      region.removeEventListener('touchstart', stop)
    }
  }, [answered])

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

  const narrow = useMediaQuery(NARROW)
  const { panel, openPanel, closePanel } = chat
  const opened = useRef(false)
  const closed = useRef<OpenPanel | null>(null)

  const shown = panel?.item ?? null
  const opener = useMemo<PanelOpener>(
    () => ({
      shown,
      open: (item, from) => {
        opened.current = true
        openPanel(item, Math.max(0, openersOf(column.current, item).indexOf(from)))
      },
    }),
    [openPanel, shown],
  )

  // Opening moves focus to the panel's heading. Closing hands it back to what opened the panel, which shows again now.
  useEffect(() => {
    if (opened.current && panel) {
      opened.current = false
      document.getElementById(PANEL_HEADING)?.focus({ preventScroll: true })
    }
    const was = closed.current
    if (!was || panel) return
    closed.current = null
    const back = openerAfterClose(openersOf(column.current, was.item), was.from) ?? document.getElementById('planner-box')
    back?.focus({ preventScroll: true })
  }, [panel])

  const close = () => {
    closed.current = panel
    closePanel()
  }

  return (
    <InChat.Provider value>
      <div className={styles['chatLayout']} data-chat>
        <div ref={column} className={styles['chat']} inert={(narrow && panel !== null) || undefined}>
          <OpensInPanel.Provider value={opener}>
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
          </OpensInPanel.Provider>
          <div className={styles['chatDock']}>{box}</div>
        </div>
        {panel ? <SidePanel key={panelKey(panel.item)} item={panel.item} now={now} narrow={narrow} onClose={close} /> : null}
      </div>
    </InChat.Provider>
  )
}
