import type { ReactNode } from 'react'
import type { Icon, IconProps } from '../ui/icons'

function drawn(name: string, shapes: ReactNode, strokeWidth = 1.75): Icon {
  function ShellIcon({ size = 20, ...rest }: IconProps) {
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
  ShellIcon.displayName = name
  return ShellIcon
}

/** Teams on the rail: a speech bubble. */
export const ChatIcon = drawn('ChatIcon', <path d="M4 5h16v11H9l-5 4z" />)

export const TicketIcon = drawn('TicketIcon', <path d="M4 8a2 2 0 0 0 0 4v0a2 2 0 0 0 0 4v2h16v-2a2 2 0 0 0 0-4v0a2 2 0 0 0 0-4V6H4zM9 6v12" />)

/** Home on the rail: a house, as in the sketch. */
export const HomeIcon = drawn(
  'HomeIcon',
  <>
    <path d="M3.5 10.5 12 3.5l8.5 7" />
    <path d="M5.5 9v11.5h13V9" />
    <path d="M10 20.5v-6h4v6" />
  </>,
)

/** Workflows on the rail: two steps joined, as in the sketch. */
export const WorkflowsIcon = drawn(
  'WorkflowsIcon',
  <>
    <rect x="3" y="4" width="6" height="6" rx="1.5" />
    <rect x="15" y="14" width="6" height="6" rx="1.5" />
    <path d="M9 7h4a3 3 0 0 1 3 3v4" />
  </>,
)

/** Settings at the rail's foot: a gear, as in the sketch. */
export const SettingsIcon = drawn(
  'SettingsIcon',
  <>
    <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
    <circle cx="12" cy="12" r="3" />
  </>,
)

/** The test controls' toggle: sliders, so it never reads as Settings. */
export const SlidersIcon = drawn(
  'SlidersIcon',
  <>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="10" cy="17" r="2" />
  </>,
  2.2,
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
