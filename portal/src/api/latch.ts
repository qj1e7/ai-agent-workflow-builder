import { useState } from 'react'

export interface Latch {
  /** Calls start unless an earlier start has not called its settled yet. */
  run(this: void, start: (settled: () => void) => void): void
}

/**
 * Lets one press start a request and drops the others until it settles. A button that guards on render state lets
 * two presses in one tick through, because the pending state draws a tick later.
 */
export function createLatch(): Latch {
  let busy = false
  return {
    run(start) {
      if (busy) return
      busy = true
      start(() => {
        busy = false
      })
    },
  }
}

export function useLatch(): Latch {
  return useState(createLatch)[0]
}

/** What a mutation calls back with. One shape for every press that goes through a latch. */
export interface Outcome<T = void> {
  onSuccess?: (value: T) => void
  onError?: (error: unknown) => void
  onSettled?: () => void
}

/** Sends one request for a press and drops the others until the platform answers. The caller's onSettled still runs. */
export function pressOnce<T>(latch: Latch, send: (outcome: Outcome<T>) => void, outcome: Outcome<T>): void {
  latch.run((settled) =>
    send({
      ...outcome,
      onSettled: () => {
        settled()
        outcome.onSettled?.()
      },
    }),
  )
}
