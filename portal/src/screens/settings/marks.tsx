import type { ReactNode } from 'react'

function Mark({ size, children }: { size: number; children: ReactNode }) {
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
    >
      {children}
    </svg>
  )
}

export function ShieldMark({ size = 16 }: { size?: number }) {
  return (
    <Mark size={size}>
      <path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.9-4.3-1.6-7.5-5.3-7.5-9.9V6z" />
      <path d="M8.5 12l2.5 2.5 4.5-5" />
    </Mark>
  )
}

export function CheckMark({ size = 14 }: { size?: number }) {
  return (
    <Mark size={size}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Mark>
  )
}

export function AlertMark({ size = 16 }: { size?: number }) {
  return (
    <Mark size={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5v.01" />
    </Mark>
  )
}

export function ClockMark({ size = 14 }: { size?: number }) {
  return (
    <Mark size={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Mark>
  )
}
