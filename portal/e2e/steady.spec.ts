import type { Browser, Page } from '@playwright/test'
import { lineEnded } from './support/flows'
import { expect, test } from './support/test'

const RUN_LIMIT_MS = 75_000
const HOLD_AFTER_MS = 3_000
/** Google's "good" cumulative layout shift is 0.1. The line should not move on its own at all, so the bar is ten times lower. */
const MAX_SHIFT = 0.01
/**
 * The replay forced about 77 layouts when the line was measured on every render, 50 ms apart through the approval
 * hold, and about 27 once it was measured only when a part could move.
 */
const MAX_FORCED_LAYOUTS_IN_REPLAY = 50
const TRACE_CATEGORIES = ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'disabled-by-default-devtools.timeline.stack']

interface Shift {
  readonly value: number
  readonly at: number
  readonly moved: readonly string[]
}

interface Probe {
  readonly shifts: Shift[]
  frames: number[]
}

declare global {
  interface Window {
    __probe?: Probe
  }
}

/** Runs in the page before the app: every layout shift with what moved, and the time between animation frames. */
function installProbe(): void {
  const probe: Probe = { shifts: [], frames: [] }
  window.__probe = probe
  const describe = (node: Node | null): string => {
    if (!(node instanceof Element)) return node?.nodeName ?? 'unknown'
    const cls = typeof node.className === 'string' && node.className ? `.${node.className.split(/\s+/)[0]}` : ''
    const stop = node.closest('[data-stop]')?.getAttribute('data-stop')
    return `${node.tagName.toLowerCase()}${cls}${stop ? ` in ${stop}` : ''}`
  }
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean; sources?: { node: Node | null }[] })[]) {
      if (entry.hadRecentInput) continue
      probe.shifts.push({ value: entry.value, at: Math.round(entry.startTime), moved: (entry.sources ?? []).map((source) => describe(source.node)) })
    }
  }).observe({ type: 'layout-shift', buffered: true })
  let last = 0
  const frame = (now: number) => {
    if (last > 0) probe.frames.push(now - last)
    last = now
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
}

function percentile(sorted: readonly number[], p: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length * p) / 100))] ?? 0
}

interface TraceEvent {
  readonly name: string
  readonly dur?: number
  readonly args?: { readonly beginData?: { readonly stackTrace?: unknown } }
}

/** Plays one part of the run under a trace, and says how much the page shifted, how smooth it was and how often script forced a layout. */
async function measure(browser: Browser, page: Page, play: () => Promise<void>) {
  const from = await page.evaluate(() => {
    if (window.__probe) window.__probe.frames = []
    return window.__probe?.shifts.length ?? 0
  })
  await browser.startTracing(page, { categories: TRACE_CATEGORIES })
  await play()
  const trace = JSON.parse((await browser.stopTracing()).toString('utf8')) as { traceEvents: TraceEvent[] }
  const { shifts, frames } = await page.evaluate((first) => ({ shifts: window.__probe?.shifts.slice(first) ?? [], frames: window.__probe?.frames ?? [] }), from)
  frames.sort((a, b) => a - b)
  const layouts = trace.traceEvents.filter((event) => event.name === 'Layout')
  const forced = layouts.filter((event) => event.args?.beginData?.stackTrace !== undefined)
  const ms = (events: readonly TraceEvent[]) => Math.round(events.reduce((sum, event) => sum + (event.dur ?? 0), 0) / 100) / 10
  return {
    layoutShift: Math.round(shifts.reduce((sum, shift) => sum + shift.value, 0) * 10_000) / 10_000,
    shifts: shifts.map((shift) => `${shift.value.toFixed(4)} at ${shift.at} ms: ${shift.moved.join(', ')}`),
    frameMs: { count: frames.length, p50: percentile(frames, 50).toFixed(1), p95: percentile(frames, 95).toFixed(1), max: (frames.at(-1) ?? 0).toFixed(1) },
    layouts: layouts.length,
    layoutMs: ms(layouts),
    forcedLayouts: forced.length,
    forcedLayoutMs: ms(forced),
  }
}

/**
 * On the phone the template lets the status region grow with its words and opens each panel inline under its stop, so
 * both move the line by design. Holding them still, and the status words out of sight, leaves only the line's own rows
 * to measure. Through the CSSOM, which the Content Security Policy allows.
 */
async function holdStatusAndPanels(page: Page): Promise<void> {
  await page.evaluate(() => {
    const sheet = document.styleSheets[0]
    sheet?.insertRule('[role="status"][aria-atomic="true"] { height: 200px; overflow: hidden; visibility: hidden; }', sheet.cssRules.length)
    sheet?.insertRule('[data-stop] > div:has(> [role="region"]) { position: absolute; }', sheet.cssRules.length)
  })
}

/** In-app, so the demo keeps its runs. On the real clock: the shared helpers move a frozen one. */
async function goTo(page: Page, link: string): Promise<void> {
  await page.getByRole('link', { name: link, exact: true }).click()
  await page.locator('#main h1').waitFor()
}

/** By CSS rather than by role, so it still finds the headline while the phone's status words are out of sight. */
const headlineText = (page: Page) => page.locator('[role="status"][aria-atomic="true"] h2')

async function untilWritten(page: Page): Promise<void> {
  await expect(headlineText(page), 'the ticket is written').toHaveText('MOCK-142 is in Jira', { timeout: RUN_LIMIT_MS })
  await expect(lineEnded(page, 'done'), 'the run finishes').toBeVisible({ timeout: RUN_LIMIT_MS })
  await page.waitForTimeout(HOLD_AFTER_MS)
}

test('the line holds still through a full 1x run and its replay, and keeps time', async ({ page, browser }, info) => {
  test.setTimeout(2 * RUN_LIMIT_MS + 30_000)
  const phone = (page.viewportSize()?.width ?? 0) < 760
  await page.addInitScript(installProbe)
  await page.goto('/')

  const live = await measure(browser, page, () => untilWritten(page))

  // Back on the overview, the run has finished, so it replays from the start, through the compressed approval wait.
  await goTo(page, 'Jira')
  if (phone) await holdStatusAndPanels(page)
  const replay = await measure(browser, page, async () => {
    await goTo(page, 'Runs')
    await expect(page.locator('li[data-gate="waiting"]'), 'the replay reaches the approval wait').toBeVisible({ timeout: RUN_LIMIT_MS })
    await untilWritten(page)
  })

  const report = { project: info.project.name, live, replay }
  console.log(`STEADY ${JSON.stringify(report)}`)
  info.annotations.push({ type: 'steady', description: JSON.stringify(report) })
  expect(replay.forcedLayouts, 'a replay hold renders every 50 ms, but measures the line only when a part could move').toBeLessThanOrEqual(MAX_FORCED_LAYOUTS_IN_REPLAY)
  if (phone) {
    expect(replay.layoutShift, `the line's own layout shift over the replay: ${replay.shifts.join('; ')}`).toBeLessThanOrEqual(MAX_SHIFT)
  } else {
    const shifts = [...live.shifts, ...replay.shifts]
    expect(live.layoutShift + replay.layoutShift, `layout shift over the run and its replay: ${shifts.join('; ')}`).toBeLessThanOrEqual(MAX_SHIFT)
  }
})
