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

/** The run line's gate. Its shackle is marked so the line can open it once the yes is given. */
export const IconGate = drawn(
  'IconGate',
  <>
    <path data-shackle="" d="M7.95 10.8V8.1a4.05 4.05 0 0 1 8.1 0v2.7" />
    <rect x="5.1" y="10.8" width="13.8" height="9.9" rx="2.4" fill="currentColor" />
  </>,
  2.7,
)

export const IconTicket = drawn(
  'IconTicket',
  <>
    <rect x="3.9" y="4.5" width="16.2" height="15" rx="2.4" />
    <path d="M7.8 9.9h8.4M7.8 14.1h5.4" />
  </>,
  2.7,
)

export const IconPause = drawn('IconPause', <path d="M9 6v12M15 6v12" />, 3)

export const IconPlay = drawn('IconPlay', <path d="M8 5.5v13l10.5-6.5z" />, 2.2)

export const IconTrash = drawn(
  'IconTrash',
  <>
    <path d="M4.5 7h15M10 7V4.5h4V7M6.5 7l1 12.5h9l1-12.5" />
    <path d="M10.5 11v5M13.5 11v5" />
  </>,
  2,
)

export const IconSearch = drawn(
  'IconSearch',
  <>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4 4" />
  </>,
  2,
)

export const IconChevronRight = drawn('IconChevronRight', <path d="M9.5 6l6 6-6 6" />, 2.2)

export const IconChevronDown = drawn('IconChevronDown', <path d="M6 9.5l6 6 6-6" />, 2.2)

export const IconChevronLeft = drawn('IconChevronLeft', <path d="M14.5 6l-6 6 6 6" />, 2.2)

export const IconAlert = drawn(
  'IconAlert',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5M12 16.5v.5" />
  </>,
  2.4,
)

export const IconClock = drawn(
  'IconClock',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3.5 2" />
  </>,
  2.2,
)

export const IconPlus = drawn('IconPlus', <path d="M12 5v14M5 12h14" />, 2.4)

export const IconPencil = drawn('IconPencil', <path d="M15.5 5.5l3 3L8 19H5v-3z" />, 2)

export const IconInfo = drawn(
  'IconInfo',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5M12 7.5v.5" />
  </>,
  2.4,
)

/** A message, as a request sent to Teams. */
export const IconMessage = drawn('IconMessage', <path d="M4.5 5.25h15a1.5 1.5 0 0 1 1.5 1.5V15a1.5 1.5 0 0 1-1.5 1.5h-8.25l-4.5 3.75V16.5H4.5A1.5 1.5 0 0 1 3 15V6.75a1.5 1.5 0 0 1 1.5-1.5z" />, 2.2)

export const IconSend = drawn('IconSend', <path d="M4 12l16-8-6 16-2.5-6.5z" />, 2)

/** An IF block: one way in, two ways out. */
export const IconFork = drawn('IconFork', <path d="M3.5 12h5.5M9 12l4.5-6H20M9 12l4.5 6H20" />, 2.4)

/** A block that ends the run quietly. */
export const IconStop = drawn(
  'IconStop',
  <>
    <circle cx="12" cy="12" r="8.2" />
    <path d="M8.2 12h7.6" />
  </>,
  2.4,
)

/** A block that tells the person, in the app. */
export const IconBell = drawn(
  'IconBell',
  <>
    <path d="M6 17.1v-6a6 6 0 0 1 12 0v6l1.8 1.8H4.2z" />
    <path d="M9.9 21a2.25 2.25 0 0 0 4.2 0" />
  </>,
  2.2,
)

/** An agent's block that weighs what was read. */
export const IconCompare = drawn('IconCompare', <path d="M4 8.5h14l-3.5-3.5M20 15.5H6l3.5 3.5" />, 2.4)
