import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { Button } from './Button'
import { cx } from './cx'
import { IconChevronDown, type Icon } from './icons'
import styles from './ActionMenu.module.css'

export interface MenuItem {
  readonly key: string
  readonly label: string
  readonly icon?: Icon
  /** A destructive item. It sits last, after a divider, in red. */
  readonly danger?: boolean
  readonly onSelect: () => void
}

type Move = 'ArrowDown' | 'ArrowUp' | 'Home' | 'End'

/** Where focus goes in a menu of `size` items when `key` is pressed on item `at`. Arrow keys wrap. */
export function focusAfter(key: Move, at: number, size: number): number {
  switch (key) {
    case 'ArrowDown':
      return (at + 1) % size
    case 'ArrowUp':
      return (at - 1 + size) % size
    case 'Home':
      return 0
    case 'End':
      return size - 1
  }
}

const MOVES: ReadonlySet<string> = new Set<Move>(['ArrowDown', 'ArrowUp', 'Home', 'End'])

interface ItemsProps {
  readonly id: string
  readonly label: string
  readonly items: readonly MenuItem[]
  readonly onPick: (item: MenuItem) => void
  readonly onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void
}

/** The open menu. Only the danger items come after the divider, so Delete cannot be hit by sliding off Run now. */
export function MenuItems({ id, label, items, onPick, onKeyDown }: ItemsProps) {
  const firstDanger = items.findIndex((item) => item.danger)
  return (
    <div id={id} className={styles['menu']} role="menu" tabIndex={-1} aria-label={label} onKeyDown={onKeyDown}>
      {items.map((item, index) => (
        <Fragment key={item.key}>
          {index === firstDanger && index > 0 ? <hr className={styles['rule']} /> : null}
          <button type="button" role="menuitem" className={cx(styles['item'], item.danger && styles['danger'])} onClick={() => onPick(item)}>
            {item.icon ? <item.icon size={18} /> : null}
            {item.label}
          </button>
        </Fragment>
      ))}
    </div>
  )
}

interface ActionMenuProps {
  readonly items: readonly MenuItem[]
  /** Reaches the menu button, so a dialog an item opens can hand focus back to it. */
  readonly buttonRef: RefObject<HTMLButtonElement | null>
  readonly label?: string
  readonly busy?: boolean
  readonly place?: string
}

/** A button that opens a menu of quieter actions. Enter, Space or the Down arrow open it, the arrow keys move, Escape closes it and focus returns to the button. */
export function ActionMenu({ items, buttonRef, label = 'More actions', busy = false, place }: ActionMenuProps) {
  const menuId = useId()
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const menuItems = () => [...(wrap.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]

  useEffect(() => {
    if (open) menuItems()[0]?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !wrap.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside, true)
    return () => document.removeEventListener('pointerdown', outside, true)
  }, [open])

  function closeToButton() {
    setOpen(false)
    buttonRef.current?.focus()
  }

  function onMenuKey(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeToButton()
      return
    }
    if (event.key === 'Tab') {
      buttonRef.current?.focus()
      setOpen(false)
      return
    }
    if (!MOVES.has(event.key)) return
    event.preventDefault()
    const all = menuItems()
    const at = all.findIndex((element) => element === document.activeElement)
    all[focusAfter(event.key as Move, Math.max(at, 0), all.length)]?.focus()
  }

  function pick(item: MenuItem) {
    closeToButton()
    item.onSelect()
  }

  return (
    <div ref={wrap} className={styles['wrap']}>
      <Button
        ref={buttonRef}
        data-place={place}
        loading={busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !open) {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {label}
        <IconChevronDown size={16} aria-hidden="true" />
      </Button>
      {open ? <MenuItems id={menuId} label={label} items={items} onPick={pick} onKeyDown={onMenuKey} /> : null}
    </div>
  )
}
