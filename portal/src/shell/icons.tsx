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

export const SettingsIcon = drawn(
  'SettingsIcon',
  <>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2" />
    <circle cx="10" cy="17" r="2" />
  </>,
)

export const HomeIcon = drawn('HomeIcon', <path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" />)

export const GridIcon = drawn(
  'GridIcon',
  <>
    <rect x="4" y="4" width="7" height="7" rx="1.5" />
    <rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" />
    <rect x="13" y="13" width="7" height="7" rx="1.5" />
  </>,
)

export const BoxIcon = drawn(
  'BoxIcon',
  <>
    <path d="M4 7.5L12 3.5l8 4v9l-8 4-8-4z" />
    <path d="M4 7.5l8 4 8-4M12 11.5v9" />
  </>,
)

export const BotIcon = drawn(
  'BotIcon',
  <>
    <rect x="4.5" y="8" width="15" height="11.5" rx="3.5" />
    <path d="M12 4.5V8M9.2 13.4v.2M14.8 13.4v.2" />
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
