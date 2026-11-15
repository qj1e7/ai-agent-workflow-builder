import type { Locator, Page } from '@playwright/test'

/** Each link of the run line, in order: the state it draws, with "+" when it marches. */
export function runLinks(scope: Page | Locator): Promise<string[]> {
  return scope
    .getByRole('list', { name: 'Steps of this run' })
    .locator('[data-link]')
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

/** Where the march's dashes are now, read twice a beat apart. Equal readings mean the dashes hold still. */
export async function marchReadings(page: Page): Promise<[string, string]> {
  const read = () => page.locator('[data-link="flow"]').first().evaluate((link) => getComputedStyle(link, '::before').transform)
  const first = await read()
  await page.waitForTimeout(150)
  return [first, await read()]
}

/** The CSS properties each animation on the run line's links changes. A cheap march changes only transform. */
export function linkAnimations(page: Page): Promise<string[][]> {
  return page
    .locator('[data-link]')
    .evaluateAll((links) =>
      links.flatMap((link) =>
        link
          .getAnimations({ subtree: true })
          .filter((animation) => animation.playState === 'running')
          .map((animation) => [...new Set((animation.effect as KeyframeEffect).getKeyframes().flatMap((frame) => Object.keys(frame)))].filter((key) => !['offset', 'computedOffset', 'easing', 'composite'].includes(key))),
      ),
    )
}
