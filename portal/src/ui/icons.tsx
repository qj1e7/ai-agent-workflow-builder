import type { ReactNode, SVGProps } from 'react'

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'children'> {
  size?: number | string
}

export type Icon = (props: IconProps) => ReactNode

function drawn(name: string, shapes: ReactNode, strokeWidth = 1.75): Icon {
  function DrawnIcon({ size = 16, ...rest }: IconProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        {...rest}
      >
        {shapes}
      </svg>
    )
  }
  DrawnIcon.displayName = name
  return DrawnIcon
}

export const IconExternal = drawn(
  'IconExternal',
  <>
    <path d="M14 5h5v5M19 5l-8 8" />
    <path d="M11 6H7.5A1.5 1.5 0 0 0 6 7.5v9A1.5 1.5 0 0 0 7.5 18h9a1.5 1.5 0 0 0 1.5-1.5V13" />
  </>,
)

export const IconCheck = drawn('IconCheck', <path d="M5 12.5l4.5 4.5L19 7.5" />, 3)

export const IconX = drawn('IconX', <path d="M6 6l12 12M18 6L6 18" />, 3)

export const IconShield = drawn(
  'IconShield',
  <>
    <path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.9-4.3-1.6-7.5-5.3-7.5-9.9V6z" />
    <path d="M8.5 12l2.5 2.5 4.5-5" />
  </>,
  2.2,
)

export const IconLock = drawn(
  'IconLock',
  <>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </>,
  2.2,
)
