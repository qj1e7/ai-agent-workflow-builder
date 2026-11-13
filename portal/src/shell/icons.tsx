import type { ReactNode } from 'react'
import type { Icon, IconProps } from '../ui/icons'

function drawn(name: string, shapes: ReactNode): Icon {
  function ShellIcon({ size = 20, ...rest }: IconProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.2}
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
  ShellIcon.displayName = name
  return ShellIcon
}

export const ChatIcon = drawn('ChatIcon', <path d="M4 5h16v11H9l-5 4z" />)

export const TicketIcon = drawn('TicketIcon', <path d="M4 8a2 2 0 0 0 0 4v0a2 2 0 0 0 0 4v2h16v-2a2 2 0 0 0 0-4v0a2 2 0 0 0 0-4V6H4zM9 6v12" />)

export const SettingsIcon = drawn(
  'SettingsIcon',
  <>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="10" cy="17" r="2" />
  </>,
)

/** Workflows on the rail: three linked nodes, as in the sketch. */
export const NodesIcon = drawn(
  'NodesIcon',
  <>
    <circle cx="5.4" cy="12" r="2.6" />
    <circle cx="18.6" cy="6" r="2.6" />
    <circle cx="18.6" cy="18" r="2.6" />
    <path d="M7.9 10.9l8.2-3.8M7.9 13.1l8.2 3.8" />
  </>,
)

/** The Watchlist on the rail: a stack of rows, as in the sketch. */
export const StackIcon = drawn(
  'StackIcon',
  <>
    <rect x="3.6" y="4.2" width="16.8" height="4.8" rx="1.4" />
    <rect x="3.6" y="9.6" width="16.8" height="4.8" rx="1.4" />
    <rect x="3.6" y="15" width="16.8" height="4.8" rx="1.4" />
  </>,
)

export function Mark({ height = 22 }: { height?: number }) {
  return (
    <svg width={Math.round((height * 228) / 144)} height={height} viewBox="4 0 228 144" aria-hidden="true" focusable="false">
      <path
        d="M30 57C34.5 75.5 34.5 75.5 53 80C34.5 84.5 34.5 84.5 30 103C25.5 84.5 25.5 84.5 7 80C25.5 75.5 25.5 75.5 30 57Z"
        fill="var(--ink)"
      />
      <g fill="var(--brand)" stroke="var(--brand)" strokeWidth={6} strokeLinejoin="round">
        <polygon points="52,58 94,58 116.6,89.4 94.4,121.6" />
        <polygon points="132.6,140 117.6,97.5 182.7,3.5 226.8,3.5" />
      </g>
    </svg>
  )
}
