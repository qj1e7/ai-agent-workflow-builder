import type { Locator, Page } from '@playwright/test'
import { showHistory } from './ui'

/**
 * Each link of the run line, in order: the state it draws, with "+" when it marches. The run page draws its links as the stage's
 * tracks, which never march: the glow on a hand-off is a dot, not dashes. The side panel's small line sits in Run history, so this
 * opens the history first when there is one.
 */
export async function runLinks(scope: Page | Locator): Promise<string[]> {
  if ((await scope.locator('[data-stage]').count()) === 0) await showHistory(scope)
  return scope
    .locator('[data-stage] [data-link], ol[aria-label="Steps of this run"] [data-link]')
    .evaluateAll((links) => links.map((link) => `${link.getAttribute('data-link') ?? ''}${link.hasAttribute('data-march') ? '+' : ''}`))
}

interface Event {
  readonly seq: number
  readonly kind: string
}

/**
 * Shows a real run as it stood when its first agent started work: the page gets the run's events up to then, and the live
 * stream never answers, so nothing moves the run on.
 */
export async function holdRunAtWork(page: Page, runId: string): Promise<void> {
  await page.route(new RegExp(`/api/v1/runs/${runId}/events`), async (route) => {
    if ((route.request().headers()['accept'] ?? '').includes('text/event-stream')) return
    const response = await route.fetch()
    const body = (await response.json()) as { events: Event[] }
    const atWork = body.events.find((event) => event.kind === 'agent_step_started')?.seq ?? 0
    await route.fulfill({ response, json: { ...body, events: body.events.filter((event) => event.seq <= atWork) } })
  })
}

/** The CSS properties each animation on the run line's links changes, and on the stage's glowing hand-offs. A cheap march changes only transform. */
export function linkAnimations(page: Page): Promise<string[][]> {
  return page
    .locator('[data-link], [data-glow]')
    .evaluateAll((links) =>
      links.flatMap((link) =>
        link
          .getAnimations({ subtree: true })
          .filter((animation) => animation.playState === 'running')
          .map((animation) => [...new Set((animation.effect as KeyframeEffect).getKeyframes().flatMap((frame) => Object.keys(frame)))].filter((key) => !['offset', 'computedOffset', 'easing', 'composite'].includes(key))),
      ),
    )
}

/**
 * Starts counting each animation the page starts, by name, from the first paint. A glowing hand-off is a dot that runs for under a second
 * and then rests, so a check that looks afterwards cannot tell it ran. Call this before `page.goto`.
 */
export async function watchGlows(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const started: string[] = []
    Object.assign(window, { animationsStarted: started })
    document.addEventListener('animationstart', (event) => started.push(event.animationName), true)
  })
}

/** How many hand-off dots (the stage's `pk` animation) the page has started since `watchGlows`. */
export function glowsStarted(page: Page): Promise<number> {
  return page.evaluate(() => ((window as unknown as { animationsStarted?: string[] }).animationsStarted ?? []).filter((name) => /pk/.test(name)).length)
}

/** The waiting gate's ring: whether its pulse runs now, or is paused (the tab is hidden or the stage is out of view). */
export function ringState(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    document
      .getAnimations()
      .filter((animation) => (animation.effect as KeyframeEffect | null)?.pseudoElement === '::after' && (animation.effect as KeyframeEffect).target?.hasAttribute('data-ring') === true)
      .map((animation) => animation.playState),
  )
}
