import type { Page } from '@playwright/test'

export interface Collision {
  at: number
  mover: string
  label: string
  overlap: { width: number; height: number }
}

export const MOVERS = '[data-travel], [data-ticket], [data-speech]'
export const LABELS = '[data-room-label]'
export const OVERLAP_PX = 1
export const SAMPLE_EVERY_MS = 100

interface SamplerState {
  collisions: Collision[]
  samples: number
  stop: () => void
}

// Runs inside the page. A collision is an overlap wider and taller than the threshold, between a visible mover and a label.
function startSampling(args: { every: number; movers: string; labels: string; threshold: number }): void {
  const opacity = (el: Element) => {
    let value = 1
    for (let node: Element | null = el; node; node = node.parentElement) value *= Number(getComputedStyle(node).opacity)
    return value
  }
  const name = (el: Element) => {
    const text = (el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40)
    const kind = ['data-travel', 'data-ticket', 'data-speech', 'data-room-label'].find((attribute) => el.hasAttribute(attribute)) ?? el.tagName.toLowerCase()
    return `${kind} "${text}"`
  }
  const shown = (selector: string) =>
    [...document.querySelectorAll(selector)]
      .filter((el) => opacity(el) > 0.05)
      .map((el) => ({ el, rect: el.getBoundingClientRect() }))
      .filter(({ rect }) => rect.width > 0 && rect.height > 0)

  const started = performance.now()
  const state: SamplerState = { collisions: [], samples: 0, stop: () => undefined }
  const timer = window.setInterval(() => {
    state.samples += 1
    const at = Math.round(performance.now() - started)
    const labels = shown(args.labels)
    for (const mover of shown(args.movers)) {
      for (const label of labels) {
        if (mover.el === label.el || mover.el.contains(label.el) || label.el.contains(mover.el)) continue
        const width = Math.min(mover.rect.right, label.rect.right) - Math.max(mover.rect.left, label.rect.left)
        const height = Math.min(mover.rect.bottom, label.rect.bottom) - Math.max(mover.rect.top, label.rect.top)
        if (width > args.threshold && height > args.threshold) {
          state.collisions.push({ at, mover: name(mover.el), label: name(label.el), overlap: { width: Math.round(width * 10) / 10, height: Math.round(height * 10) / 10 } })
        }
      }
    }
  }, args.every)
  state.stop = () => window.clearInterval(timer)
  ;(window as unknown as { e2eSampler: SamplerState }).e2eSampler = state
}

export async function collisionSampler(page: Page): Promise<{ stop: () => Promise<{ collisions: Collision[]; samples: number }> }> {
  await page.evaluate(startSampling, { every: SAMPLE_EVERY_MS, movers: MOVERS, labels: LABELS, threshold: OVERLAP_PX })
  return {
    stop: () =>
      page.evaluate(() => {
        const state = (window as unknown as { e2eSampler: SamplerState }).e2eSampler
        state.stop()
        return { collisions: state.collisions, samples: state.samples }
      }),
  }
}
