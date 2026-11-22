import type { AnchorHTMLAttributes, ButtonHTMLAttributes, MouseEvent, ReactNode, Ref } from 'react'
import type { LinkProps } from 'react-router'
import { Link } from './Link'
import { IconExternal, type Icon } from './icons'
import { cx } from './cx'
import styles from './Button.module.css'

/** Primary is the one filled button in a view. The others are outlined. */
export type ButtonVariant = 'primary' | 'secondary' | 'danger-outline'

/** The sketch's two heights: 38 px, or 32 px for a button inside a row or a tile. */
export type ButtonSize = 'regular' | 'small'

const variantClass: Record<ButtonVariant, string | undefined> = {
  primary: styles['primary'],
  secondary: styles['secondary'],
  'danger-outline': styles['dangerOutline'],
}

export function buttonClassName(variant: ButtonVariant = 'secondary', size: ButtonSize = 'regular'): string {
  return cx(styles['button'], variantClass[variant], size === 'small' && styles['small'])
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  ref?: Ref<HTMLButtonElement>
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: Icon
}

export function Button({ variant = 'secondary', size = 'regular', loading = false, icon: Leading, onClick, children, ...rest }: ButtonProps) {
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
      className={buttonClassName(variant, size)}
      aria-disabled={inactive || undefined}
      aria-busy={loading || undefined}
      onClick={handleClick}
    >
      {loading ? <span className={styles['spinner']} aria-hidden="true" /> : Leading ? <Leading size={16} /> : null}
      {children}
    </button>
  )
}

interface ButtonLinkProps extends Omit<LinkProps, 'className'> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: Icon
}

export function ButtonLink({ variant = 'secondary', size = 'regular', icon: Leading, children, ...rest }: ButtonLinkProps) {
  return (
    <Link {...rest} className={buttonClassName(variant, size)}>
      {Leading ? <Leading size={16} /> : null}
      {children}
    </Link>
  )
}

interface ButtonAnchorProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'className' | 'target' | 'rel'> {
  variant?: ButtonVariant
  size?: ButtonSize
  children: ReactNode
}

export function ButtonAnchor({ variant = 'secondary', size = 'regular', children, ...rest }: ButtonAnchorProps) {
  return (
    <a {...rest} className={buttonClassName(variant, size)} target="_blank" rel="noopener noreferrer">
      {children}
      <IconExternal size={16} />
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  )
}
