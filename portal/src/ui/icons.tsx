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

export const IconCheck = drawn('IconCheck', <path d="M5 12.5l4.5 4.5L19 7.5" />)
export const IconX = drawn('IconX', <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />)
export const IconClock = drawn(
  'IconClock',
  <>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </>,
)
export const IconLock = drawn(
  'IconLock',
  <>
    <rect x="5" y="10.5" width="14" height="9.5" rx="2" />
    <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
  </>,
)
export const IconUnlock = drawn(
  'IconUnlock',
  <>
    <rect x="5" y="10.5" width="14" height="9.5" rx="2" />
    <path d="M8 10.5V8a4 4 0 0 1 7.6-1.7" />
  </>,
)
export const IconAlert = drawn(
  'IconAlert',
  <>
    <path d="M12 4l9 16H3z" />
    <path d="M12 10v4.5M12 17.2v.1" />
  </>,
)
export const IconTicket = drawn(
  'IconTicket',
  <>
    <path d="M4 7.5A1.5 1.5 0 0 1 5.5 6h13A1.5 1.5 0 0 1 20 7.5V10a2 2 0 0 0 0 4v2.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 16.5V14a2 2 0 0 0 0-4z" />
    <path d="M14 6v12" strokeDasharray="2 2.5" />
  </>,
)
export const IconTag = drawn(
  'IconTag',
  <>
    <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h6.6a1.5 1.5 0 0 1 1 .4l7 7a1.5 1.5 0 0 1 0 2.1l-5.6 5.6a1.5 1.5 0 0 1-2.1 0l-7-7a1.5 1.5 0 0 1-.4-1z" />
    <circle cx="8.5" cy="8.5" r="1.3" />
  </>,
)
export const IconRepo = drawn(
  'IconRepo',
  <>
    <path d="M6 4.5h11.5V18H7.5A1.5 1.5 0 0 0 6 19.5z" />
    <path d="M6 19.5A1.5 1.5 0 0 0 7.5 21h10v-3" />
    <path d="M9.5 8.5h5" />
  </>,
)
export const IconChat = drawn(
  'IconChat',
  <>
    <path d="M4.5 6.5A2 2 0 0 1 6.5 4.5h11a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H11l-4 3.5v-3.5h-.5a2 2 0 0 1-2-2z" />
    <path d="M8.5 9h7M8.5 12h4.5" />
  </>,
)
export const IconShield = drawn(
  'IconShield',
  <>
    <path d="M12 3.5l7 2.5v5.5c0 4.3-3 7.6-7 9-4-1.4-7-4.7-7-9V6z" />
    <path d="M8.8 12.2l2.2 2.2 4.2-4.4" />
  </>,
)
export const IconReplay = drawn(
  'IconReplay',
  <>
    <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
    <path d="M4.5 4.5v4h4" />
  </>,
)
export const IconCopy = drawn(
  'IconCopy',
  <>
    <rect x="8.5" y="8.5" width="11" height="11" rx="2" />
    <path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" />
  </>,
)
export const IconWave = drawn('IconWave', <path d="M5 12h2M9 8v8M13 5v14M17 9v6M20 11.5v1" />)
export const IconDoor = drawn(
  'IconDoor',
  <>
    <path d="M5 20.5h14M7 20.5V4.5h10v16" />
    <path d="M14 12.5h.1" />
  </>,
)
export const IconFlow = drawn(
  'IconFlow',
  <>
    <rect x="3.5" y="4" width="6" height="5" rx="1.2" />
    <rect x="14.5" y="15" width="6" height="5" rx="1.2" />
    <path d="M6.5 9v3.5a2 2 0 0 0 2 2h6" />
  </>,
)
export const IconGear = drawn(
  'IconGear',
  <>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6" />
    <circle cx="12" cy="12" r="6.3" />
  </>,
)
export const IconPerson = drawn(
  'IconPerson',
  <>
    <circle cx="12" cy="8.5" r="3.5" />
    <path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" />
  </>,
)
export const IconPlay = drawn('IconPlay', <path d="M8 5.5v13l10.5-6.5z" />)
export const IconFastForward = drawn('IconFastForward', <path d="M3.5 6.5v11L11 12zM12.5 6.5v11L20 12z" />)
export const IconPause = drawn('IconPause', <path d="M8.5 5.5v13M15.5 5.5v13" />)
export const IconArrow = drawn('IconArrow', <path d="M5 12h14M13.5 6.5L19 12l-5.5 5.5" />)
export const IconChevronDown = drawn('IconChevronDown', <path d="M6.5 9.5l5.5 5.5 5.5-5.5" />)
export const IconExternal = drawn(
  'IconExternal',
  <>
    <path d="M14 5h5v5M19 5l-8 8" />
    <path d="M11 6H7.5A1.5 1.5 0 0 0 6 7.5v9A1.5 1.5 0 0 0 7.5 18h9a1.5 1.5 0 0 0 1.5-1.5V13" />
  </>,
)
export const IconDot = drawn('IconDot', <circle cx="12" cy="12" r="4" />)
export const IconRing = drawn('IconRing', <circle cx="12" cy="12" r="7.5" />)
export const IconDash = drawn('IconDash', <path d="M7 12h10" />)
export const IconBox = drawn(
  'IconBox',
  <>
    <path d="M3.5 7.5L12 3.5l8.5 4v9L12 20.5l-8.5-4z" />
    <path d="M3.5 7.5L12 11.5l8.5-4M12 11.5v9" />
  </>,
)
export const IconDoc = drawn(
  'IconDoc',
  <>
    <path d="M6 3.5h8l4 4v13H6z" />
    <path d="M14 3.5v4h4M9 12h6M9 16h4" />
  </>,
)
export const IconSpinner = drawn('IconSpinner', <path d="M12 4a8 8 0 1 1-8 8" />)
export const IconFlag = drawn('IconFlag', <path d="M6.5 20.5v-16M6.5 5h11l-2.5 4 2.5 4h-11" />)
export const IconChevronUp = drawn('IconChevronUp', <path d="M6.5 14.5l5.5-5.5 5.5 5.5" />)

export const GlyphPlatform = drawn(
  'GlyphPlatform',
  <>
    <rect x="4" y="4" width="16" height="16" rx="3" />
    <path d="M8 12h8M12 8v8" />
  </>,
)
