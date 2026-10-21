import { afterEach, describe, expect, it, vi } from 'vitest'
import { followLayout } from './place'

class StillObserver {
  observe(): void {}
  disconnect(): void {}
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('following the layout', () => {
  it('places the line again when the web font arrives, but not once the line is gone', async () => {
    vi.stubGlobal('ResizeObserver', StillObserver)
    const replace = vi.fn()
    let arrive = () => undefined as void
    const fontsReady = new Promise<void>((resolve) => {
      arrive = resolve
    })
    const stop = followLayout({} as HTMLElement, replace, fontsReady)
    stop()
    arrive()
    await fontsReady
    await Promise.resolve()
    expect(replace, 'the font arrived after the line unmounted').not.toHaveBeenCalled()

    const live = followLayout({} as HTMLElement, replace, Promise.resolve())
    await Promise.resolve()
    await Promise.resolve()
    expect(replace, 'the font arrived while the line is up').toHaveBeenCalledTimes(1)
    live()
  })
})
