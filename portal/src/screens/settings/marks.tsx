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

/** The sketch's small icon for each system on its Connections card. */
export function SystemMark({ id }: { id: string }) {
  return (
    <svg viewBox="0 0 16 16" width={22} height={22} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {id === 'jira' ? (
        <>
          <rect x="2.6" y="3" width="10.8" height="10" rx="1.6" />
          <path d="M5.2 6.6h5.6M5.2 9.4h3.6" />
        </>
      ) : id === 'github' ? (
        <path d="M5.5 5L2.5 8l3 3M10.5 5l3 3-3 3" />
      ) : id === 'confluence' ? (
        <path d="M3.5 12.5v-9a1.4 1.4 0 0 1 1.4-1.4h7.6v10H4.9a1.4 1.4 0 0 0 0 2.8h7.6" />
      ) : (
        <path d="M3 3.5h10a1 1 0 0 1 1 1v5.5a1 1 0 0 1-1 1H7.5L4.5 13.5v-2.5H3a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z" />
      )}
    </svg>
  )
}
