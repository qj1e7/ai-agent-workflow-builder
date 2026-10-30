export function readMs(text: string): number {
  return Math.min(10_000, 2_000 + text.length * 45)
}

export const RESUME_MS = 4_000

export type Hold = 'hover' | 'focus' | 'hidden'

export interface ToastClock {
  hold(reason: Hold): void
  release(reason: Hold): void
  stop(): void
}

export function startToastClock(ms: number, onTimeout: () => void): ToastClock {
  const holds = new Set<Hold>()
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  const arm = (after: number) => {
    clearTimeout(timer)
    timer = setTimeout(onTimeout, after)
  }
  arm(ms)
  return {
    hold(reason) {
      holds.add(reason)
      clearTimeout(timer)
    },
    release(reason) {
      if (!holds.delete(reason)) return
      if (!stopped && holds.size === 0) arm(RESUME_MS)
    },
    stop() {
      stopped = true
      clearTimeout(timer)
    },
  }
}
