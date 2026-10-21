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
