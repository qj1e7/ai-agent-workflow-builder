import type { AnchorHTMLAttributes, ButtonHTMLAttributes, MouseEvent, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router'
import { IconExternal, type Icon } from './icons'
import { cx } from './cx'
import styles from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'danger-outline' | 'approve'

const variantClass: Record<ButtonVariant, string | undefined> = {
  primary: styles['primary'],
  secondary: styles['secondary'],
  'danger-outline': styles['dangerOutline'],
  approve: styles['approve'],
}

export function buttonClassName(variant: ButtonVariant = 'secondary'): string {
  return cx(styles['button'], variantClass[variant])
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  loading?: boolean
  icon?: Icon
}

export function Button({ variant = 'secondary', loading = false, icon: Leading, onClick, children, ...rest }: ButtonProps) {
  // aria-disabled instead of disabled, so focus stays put while the action runs
  const inactive = loading || rest.disabled === true
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (inactive) {
      event.preventDefault()
      return
    }
    onClick?.(event)
  }
  return (
    <button
      type="button"
      {...rest}
      disabled={false}
      className={buttonClassName(variant)}
      aria-disabled={inactive || undefined}
      aria-busy={loading || undefined}
      onClick={handleClick}
    >
      {loading ? <span className={styles['spinner']} aria-hidden="true" /> : Leading ? <Leading size={18} /> : null}
      {children}
    </button>
  )
}

interface ButtonLinkProps extends Omit<LinkProps, 'className'> {
  variant?: ButtonVariant
  icon?: Icon
}

export function ButtonLink({ variant = 'secondary', icon: Leading, children, ...rest }: ButtonLinkProps) {
  return (
    <Link {...rest} className={buttonClassName(variant)}>
      {Leading ? <Leading size={18} /> : null}
      {children}
    </Link>
  )
}

interface ButtonAnchorProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'className' | 'target' | 'rel'> {
  variant?: ButtonVariant
  children: ReactNode
}

export function ButtonAnchor({ variant = 'secondary', children, ...rest }: ButtonAnchorProps) {
  return (
    <a {...rest} className={buttonClassName(variant)} target="_blank" rel="noopener noreferrer">
      {children}
      <IconExternal size={16} />
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  )
}
