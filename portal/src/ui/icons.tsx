import type { ReactNode, SVGProps } from 'react'

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'children'> {
  size?: number | string
}

export type Icon = (props: IconProps) => ReactNode

function drawn(name: string, shapes: ReactNode): Icon {
  function DrawnIcon({ size = 16, ...rest }: IconProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
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
