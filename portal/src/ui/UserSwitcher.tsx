import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useCacheScope } from '../api/context'
import { rolesLabel } from '../api/labels'
import { useDevUsers } from '../api/queries'
import type { DevSession } from '../api/session'
import { Avatar } from './Avatar'
import { cx } from './cx'
import { IconCheck, IconChevronDown } from './icons'
import { tourStop } from '../tour/stops'
import styles from './UserSwitcher.module.css'

export function UserSwitcher({ session }: { session: DevSession }) {
  const userId = useCacheScope()
  const { data: users, isError } = useDevUsers()
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const current = users?.find((user) => user.id === userId)
  const name = current?.display ?? userId

  const items = () => Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])

  useEffect(() => {
    if (!open) return
    const list = items()
    const checked = list.find((item) => item.getAttribute('aria-checked') === 'true')
    ;(checked ?? list[0])?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    function closeOnOutsidePress(event: PointerEvent) {
      const target = event.target as Node
      if (!menuRef.current?.contains(target) && !buttonRef.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePress)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePress)
  }, [open])

  function closeAndReturn() {
    setOpen(false)
    buttonRef.current?.focus()
  }

  function onButtonKeyDown(event: KeyboardEvent) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setOpen(true)
    }
  }

  function onMenuKeyDown(event: KeyboardEvent) {
    const list = items()
    const index = list.indexOf(document.activeElement as HTMLElement)
    const move = (to: number) => {
      event.preventDefault()
      list[(to + list.length) % list.length]?.focus()
    }
    if (event.key === 'ArrowDown') move(index + 1)
    else if (event.key === 'ArrowUp') move(index - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(list.length - 1)
    else if (event.key === 'Escape') {
      event.preventDefault()
      closeAndReturn()
    } else if (event.key === 'Tab') setOpen(false)
  }

  function choose(id: string) {
    session.choose(id)
    closeAndReturn()
  }

  return (
    <div className={styles['switcher']}>
      <button
        ref={buttonRef}
        type="button"
        className={styles['trigger']}
        {...tourStop('user-menu')}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={onButtonKeyDown}
      >
        <Avatar kind="person" name={name} size={32} />
        <span className={styles['who']}>
          <span className={styles['name']}>{name}</span>
          {current ? <span className={styles['role']}>{rolesLabel(current.roles)}</span> : null}
        </span>
        <IconChevronDown size={16} className={cx(styles['chevron'], open && styles['chevronOpen'])} />
        <span className="visually-hidden">Switch user</span>
      </button>
      {open ? (
        <div ref={menuRef} id={menuId} role="menu" tabIndex={-1} aria-label="Switch user" className={styles['menu']} onKeyDown={onMenuKeyDown}>
          {isError || !users ? (
            <p className={styles['empty']}>{isError ? 'The list of users could not be loaded.' : 'Loading users.'}</p>
          ) : (
            users.map((user) => (
              <button
                key={user.id}
                type="button"
                role="menuitemradio"
                aria-checked={user.id === userId}
                tabIndex={-1}
                className={styles['item']}
                onClick={() => choose(user.id)}
              >
                <Avatar kind="person" name={user.display} size={32} />
                <span className={styles['who']}>
                  <span className={styles['name']}>{user.display}</span>
                  <span className={styles['role']}>{rolesLabel(user.roles)}</span>
                </span>
                {user.id === userId ? <IconCheck size={18} /> : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}
