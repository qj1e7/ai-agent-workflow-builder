type Update<T> = T | ((now: T) => T)

/**
 * React's state hooks kept outside React, so a test can call a component as a function, press what it drew, and call it again
 * with its state kept. The Portal has no DOM in its tests. Effects never run. A test file installs it with
 * `vi.mock('react', async (real) => (await import('…/ui/testHooks')).withTestHooks(await real()))`.
 */
function createTestHooks() {
  const slots: unknown[] = []
  let next = 0
  let ids = 0
  let changed = false

  function slot<T>(make: () => T): [T, number] {
    const at = next
    next += 1
    if (!(at in slots)) slots[at] = make()
    return [slots[at] as T, at]
  }

  const react = {
    useState<T>(initial: T | (() => T)): [T, (update: Update<T>) => void] {
      const [value, at] = slot(() => (typeof initial === 'function' ? (initial as () => T)() : initial))
      return [
        value,
        (update) => {
          slots[at] = typeof update === 'function' ? (update as (now: T) => T)(slots[at] as T) : update
          changed = true
        },
      ]
    },
    useRef: <T>(initial: T) => slot(() => ({ current: initial }))[0],
    useEffect: () => undefined,
    useLayoutEffect: () => undefined,
    useCallback: <T>(callback: T) => callback,
    useMemo: <T>(make: () => T) => make(),
    useId: () => {
      ids += 1
      return `:t${ids}:`
    },
  }

  return {
    react,
    /** Calls the component as React would, again while it sets its own state as it draws, and returns what it drew. */
    draw<T>(component: () => T): T {
      for (let pass = 0; pass < 5; pass += 1) {
        next = 0
        changed = false
        const drawn = component()
        if (!changed) return drawn
      }
      throw new Error('the component kept setting its state as it drew')
    },
    reset() {
      slots.length = 0
      next = 0
    },
  }
}

export const testHooks = createTestHooks()

export const withTestHooks = <M extends object>(real: M): M => ({ ...real, ...testHooks.react })
