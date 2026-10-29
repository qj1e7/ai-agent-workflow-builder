/**
 * The checker's own checks for P7's live lanes and perf block (docs/design/rebuild-plan.md).
 * Run through scripts/checks/p7.sh, which picks the stack and the lane with --grep @laneN.
 * Evidence goes to $EVID/lane-<n>/ with the file names the plan gives.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p7'
const AUTH = process.env['E2E_AUTH'] ?? 'dev'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')

const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 }
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const PLATFORM_AGENTS = ['Planner', 'AI troubleshooter']
const PLATFORM_NOTE = 'only the team that runs the platform can change it'

interface Card {
  card_id: string
  name: string
  tools: string[]
}
interface Tool {
  id: string
  name: string
  kind: 'read' | 'write'
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function devContext(browser: Browser, user: string, { phone = false }: { phone?: boolean } = {}): Promise<BrowserContext> {
  const context = await browser.newContext({
    viewport: phone ? PHONE : DESKTOP,
    ...(phone ? { isMobile: true, hasTouch: true } : {}),
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
  await context.addInitScript((id) => {
    try {
      window.localStorage.setItem('portal.dev-user', id)
    } catch {
      // A storage-less page signs in as the default user.
    }
  }, user)
  return context
}

const h1 = (page: Page) => page.locator('main h1')
const dialogOf = (page: Page) => page.locator('main dialog[open]')
const tiles = (page: Page) => page.locator('main article h3 a')

async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
}

async function shotTo(page: Page, file: string, fullPage = false): Promise<void> {
  await settle(page)
  mkdirSync(path.dirname(file), { recursive: true })
  await page.screenshot({ path: file, caret: 'hide', fullPage })
}

function onlyDev(): void {
  test.skip(AUTH !== 'dev', 'needs dev sign-in')
}

/** Opens the page and returns what the platform answered for the cards and the tools. */
async function openLibrary(page: Page, url = '/agents'): Promise<{ cards: Card[]; tools: Tool[] | null }> {
  const cardsReply = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/agent-cards')
  const toolsReply = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/tools').catch(() => null)
  await page.goto(url)
  await expect(h1(page)).toHaveText('Agent library')
  const cards = ((await (await cardsReply).json()) as { cards: Card[] }).cards
  const reply = await toolsReply
  const tools = reply?.ok() ? ((await reply.json()) as { tools: Tool[] }).tools : null
  await expect(tiles(page), 'every tile has drawn').toHaveCount(PLATFORM_AGENTS.length + cards.length)
  return { cards, tools }
}

// Lane 1. Trunk has no Agent library; at head every card appears once, beside the two platform agents.
test('@lane1 the library lists every card once, beside the two platform agents', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  if (TARGET === 'trunk') {
    await page.goto('/agents')
    await expect(h1(page)).toBeVisible()
    save(1, 'p7-library-trunk.json', { target: 'trunk', heading: await h1(page).innerText(), main: await page.locator('main').innerText() })
    await shotTo(page, path.join(laneDir(1), 'p7-library-trunk.png'))
    await context.close()
    return
  }
  const { cards } = await openLibrary(page)
  const names = (await tiles(page).allInnerTexts()).map((name) => name.trim())
  await shotTo(page, path.join(laneDir(1), 'p7-library.png'), true)
  save(1, 'p7-library.json', { target: TARGET, cards: cards.map((c) => c.name), tiles: names })
  for (const name of [...PLATFORM_AGENTS, ...cards.map((c) => c.name)]) expect(names.filter((n) => n === name), `${name} appears once`).toHaveLength(1)
  expect(names, 'nothing else is listed').toHaveLength(PLATFORM_AGENTS.length + cards.length)
  await expect(page.locator('main').getByText('Platform agent', { exact: true })).toHaveCount(PLATFORM_AGENTS.length)
  await context.close()
})

// Lane 2. The Version checker opens and lists its tools.
test('@lane2 the Version checker opens and lists its tools', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const { cards, tools } = await openLibrary(page)
  const card = cards.find((c) => c.name === 'Version checker')
  expect(card, 'the platform has a Version checker card').toBeDefined()
  await page.getByRole('link', { name: 'Version checker', exact: true }).click()
  const dialog = dialogOf(page)
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Version checker', level: 2 })).toBeVisible()
  const listed = await dialog.locator('[data-tool-id]').evaluateAll((rows) => rows.map((row) => row.getAttribute('data-tool-id')))
  await shotTo(page, path.join(laneDir(2), 'p7-card.png'))
  save(2, 'p7-card.json', { cardTools: card?.tools, listed, url: page.url() })
  expect(listed).toEqual(card?.tools)
  for (const id of card?.tools ?? []) await expect(dialog).toContainText(tools?.find((t) => t.id === id)?.name ?? id)
  await context.close()
})

// Lane 3. The Tools tab marks jira.create_ticket as a write that waits for a yes.
test('@lane3 the Tools tab marks jira.create_ticket as a write that waits for a yes', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const { tools } = await openLibrary(page)
  await page.getByRole('button', { name: /^Tools/ }).click()
  const rows = page.locator('main li[data-tool-id]')
  await expect(rows.first()).toBeVisible()
  const row = page.locator('main li[data-tool-id="jira.create_ticket"]')
  await shotTo(page, path.join(laneDir(3), 'p7-tools.png'), true)
  save(3, 'p7-tools.json', { api: tools, shown: await rows.allInnerTexts() })
  await expect(rows).toHaveCount(tools?.length ?? 0)
  await expect(row).toContainText('Changes data')
  await expect(row).toContainText('Waits for a yes')
  for (const tool of (tools ?? []).filter((t) => t.kind === 'read')) await expect(page.locator(`main li[data-tool-id="${tool.id}"]`)).toContainText('Reads only')
  await context.close()
})

// Lane 4. The Planner says only the team that runs the platform can change it.
test('@lane4 the Planner says only the team that runs the platform can change it', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await openLibrary(page)
  await page.getByRole('link', { name: 'Planner', exact: true }).click()
  const dialog = dialogOf(page)
  await expect(dialog).toBeVisible()
  await shotTo(page, path.join(laneDir(4), 'p7-platform-agent.png'))
  save(4, 'p7-platform-agent.json', { url: page.url(), text: await dialog.innerText() })
  await expect(dialog).toContainText(PLATFORM_NOTE)
  await expect(dialog.locator('textarea, input')).toHaveCount(0)
  await context.close()
})

// Lane 5. bob, Approver only, sees the same cards and no change controls.
test('@lane5 bob sees the same cards with no change controls', async ({ browser }) => {
  onlyDev()
  const seen: Record<string, string[]> = {}
  for (const user of ['alice', 'bob']) {
    const context = await devContext(browser, user)
    const page = await context.newPage()
    await openLibrary(page)
    seen[user] = (await tiles(page).allInnerTexts()).map((name) => name.trim())
    if (user === 'bob') {
      const controls = await page.locator('main').evaluate((main) => [...main.querySelectorAll('textarea, input, select, [contenteditable]')].length)
      await shotTo(page, path.join(laneDir(5), 'p7-approver.png'), true)
      await page.getByRole('link', { name: 'Version checker', exact: true }).click()
      await expect(dialogOf(page)).toBeVisible()
      const buttons = await dialogOf(page)
        .getByRole('button')
        .evaluateAll((all) => all.map((button) => (button.getAttribute('aria-label') ?? button.textContent ?? '').trim()))
      save(5, 'p7-approver.json', { tiles: seen, controls, dialogButtons: buttons, me: await page.getByRole('banner').innerText() })
      expect(controls, 'no field to type a change in').toBe(0)
      expect(buttons.length, 'the dialog has a Close button').toBeGreaterThan(0)
      expect(new Set(buttons), 'the dialog offers only Close').toEqual(new Set(['Close']))
      await expect(page.getByRole('banner')).toContainText('Bob')
    }
    await context.close()
  }
  expect(seen['bob']).toEqual(seen['alice'])
})

// Lane 6. A card opens from its URL, and closing it puts focus back on its tile.
test('@lane6 a card opens from its URL and closing returns focus to its tile', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const { cards } = await openLibrary(page)
  const card = cards.find((c) => c.name === 'Version checker')
  const url = `/agents/${card?.card_id ?? 'crd_version_checker'}`
  await page.goto(url)
  const dialog = dialogOf(page)
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Version checker', level: 2 })).toBeVisible()
  await shotTo(page, path.join(laneDir(6), 'p7-deep-link.png'))
  await dialog.getByRole('button', { name: 'Close' }).first().click()
  await expect(dialog).toHaveCount(0)
  await expect(page).toHaveURL(/\/agents$/)
  const tile = page.getByRole('link', { name: 'Version checker', exact: true })
  await expect(tile, 'focus is back on the card’s tile').toBeFocused()
  await shotTo(page, path.join(laneDir(6), 'p7-deep-link-closed.png'))
  // Opened by a click, Escape closes it and focus returns the same way.
  await tile.click()
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(tile).toBeFocused()
  save(6, 'p7-deep-link.json', { url, afterClose: new URL(page.url()).pathname })
  await context.close()
})

// Lane 7. Tab stays inside an open card, and Escape closes it.
// With one focusable element, Tab could never show focus moving inside, so the lane first proves there are more.
const TAB_STOPS = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
test('@lane7 Tab stays inside an open card and Escape closes it', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await openLibrary(page)
  await page.getByRole('link', { name: 'Version checker', exact: true }).click()
  const dialog = dialogOf(page)
  await expect(dialog).toBeVisible()
  const focusable = await dialog.locator(TAB_STOPS).count()
  expect(focusable, 'the card has more than one focusable element').toBeGreaterThan(1)
  const stops: { press: string; tag: string; label: string; inside: boolean; stop: number }[] = []
  const presses = [...Array.from({ length: focusable + 2 }, () => 'Tab'), ...Array.from({ length: focusable + 2 }, () => 'Shift+Tab')]
  for (const key of presses) {
    await page.keyboard.press(key)
    stops.push(
      await page.evaluate(
        ([press, selector]) => {
          const el = document.activeElement as HTMLElement | null
          const box = el?.closest('dialog[open]') ?? null
          const stop = box && el ? [...box.querySelectorAll(selector)].indexOf(el) : -1
          return { press, tag: el?.tagName.toLowerCase() ?? '', label: (el?.getAttribute('aria-label') ?? el?.textContent ?? '').trim().slice(0, 40), inside: box !== null, stop }
        },
        [key, TAB_STOPS] as const,
      ),
    )
  }
  await shotTo(page, path.join(laneDir(7), 'p7-dialog-tab.png'))
  save(7, 'p7-dialog-tab.json', { focusable, stops })
  expect(stops.filter((s) => !s.inside), 'focus never leaves the dialog').toEqual([])
  expect(new Set(stops.map((s) => s.stop)).size, 'Tab visits every focusable element').toBe(focusable)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await context.close()
})

// Lane 8. 390 px: the cards stack and nothing scrolls sideways.
test('@lane8 at 390 px the cards stack and nothing scrolls sideways', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice', { phone: true })
  const page = await context.newPage()
  await openLibrary(page)
  const measure = () =>
    page.evaluate(() => {
      const de = document.documentElement
      window.scrollBy(400, 0)
      const moved = window.scrollX
      window.scrollTo(0, window.scrollY)
      return { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, moved }
    })
  const boxes = await page.locator('main article').evaluateAll((els) => els.map((el) => el.getBoundingClientRect()).map((r) => ({ left: r.left, right: r.right, top: r.top })))
  const widths = [await measure()]
  await shotTo(page, path.join(laneDir(8), 'p7-phone.png'), true)
  await page.getByRole('button', { name: /^Tools/ }).click()
  await expect(page.locator('main li[data-tool-id]').first()).toBeVisible()
  widths.push(await measure())
  await page.getByRole('button', { name: /^Agents/ }).click()
  await page.getByRole('link', { name: 'Version checker', exact: true }).click()
  await expect(dialogOf(page)).toBeVisible()
  widths.push(await measure())
  const dialogBox = await dialogOf(page).boundingBox()
  save(8, 'p7-phone.json', { boxes, widths, dialogBox })
  expect(new Set(boxes.map((b) => Math.round(b.left))).size, 'every card starts at the same left edge').toBe(1)
  expect(boxes.map((b) => b.top), 'each card sits below the one before').toEqual([...boxes.map((b) => b.top)].sort((a, b) => a - b))
  expect(new Set(boxes.map((b) => Math.round(b.top))).size, 'no two cards share a row').toBe(boxes.length)
  for (const w of widths) {
    expect(w.scrollWidth).toBeLessThanOrEqual(w.clientWidth)
    expect(w.moved).toBe(0)
  }
  expect((dialogBox?.x ?? -1) >= 0 && (dialogBox?.x ?? 0) + (dialogBox?.width ?? 0) <= PHONE.width, 'the dialog fits in 390 px').toBe(true)
  await context.close()
})

// Lane 9. axe on the page, the Tools tab and an open card, at 1440 and 390 px.
test('@lane9 axe finds no WCAG 2.2 AA problem', async ({ browser }) => {
  onlyDev()
  const runs: Record<string, unknown>[] = []
  for (const [size, phone] of [
    ['1440', false],
    ['390', true],
  ] as const) {
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    await openLibrary(page)
    const run = async (name: string) => {
      await settle(page)
      const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
      runs.push({
        view: name,
        width: size,
        axe: result.testEngine.version,
        violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
        incomplete: result.incomplete.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
        passes: result.passes.length,
      })
    }
    await run('library')
    await page.getByRole('link', { name: 'Version checker', exact: true }).click()
    await expect(dialogOf(page)).toBeVisible()
    await run('open card')
    await page.keyboard.press('Escape')
    await page.getByRole('link', { name: 'Planner', exact: true }).click()
    await expect(dialogOf(page)).toBeVisible()
    await run('open Planner')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: /^Tools/ }).click()
    await expect(page.locator('main li[data-tool-id]').first()).toBeVisible()
    await run('tools tab')
    await context.close()
  }
  const total = runs.reduce((sum, run) => sum + (run['violations'] as unknown[]).length, 0)
  save(9, 'p7-axe.json', { tags: WCAG_22_AA, totalViolations: total, runs })
  expect(
    runs.flatMap((run) => (run['violations'] as { id: string; impact: string }[]).map((v) => `${String(run['view'])} @${String(run['width'])}: ${v.id} (${v.impact})`)),
    'axe violations',
  ).toEqual([])
})

// Lane 10. With the agent runtime stopped (p7.sh stops it), the Tools tab says the list is not available and the cards stay.
// GET /api/v1/tools answers from a fixed list in platform-api, so it may still answer 200 with the runtime down.
// The first pass records what the real route did. The second pass forces a 503 on that route, so the page's own handling is seen either way.
const LANE_10_PASSES_THROUGH =
  'GET /api/v1/tools answers from a fixed list in platform-api, so stopping the agent runtime does not make it fail. This lane passes through its forced 503 on that route, not through the stopped runtime.'
test('@lane10 the Tools tab says the tool list is not available and keeps the cards', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const real = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/tools').then((r) => r.status())
  const cardsReal = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/agent-cards')
  await page.goto('/agents')
  await expect(h1(page)).toHaveText('Agent library')
  const cardCount = ((await (await cardsReal).json()) as { cards: Card[] }).cards.length
  await expect(tiles(page), 'every tile has drawn').toHaveCount(PLATFORM_AGENTS.length + cardCount)
  const cardsShownReal = await tiles(page).count()
  const realStatus = await real.catch(() => -1)
  save(10, 'p7-runtime-down-real.json', { runtimeStopped: process.env['EXPECT_DOWN'] === '1', toolsStatus: realStatus, tiles: cardsShownReal, passesThrough: LANE_10_PASSES_THROUGH })
  await page.close()

  const forced = await context.newPage()
  await forced.route('**/api/v1/tools', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'The agent runtime did not answer' }) }))
  const cardsForced = forced.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/agent-cards')
  await forced.goto('/agents')
  await expect(h1(forced)).toHaveText('Agent library')
  const forcedCount = ((await (await cardsForced).json()) as { cards: Card[] }).cards.length
  await expect(tiles(forced), 'every tile has drawn').toHaveCount(PLATFORM_AGENTS.length + forcedCount)
  const before = await tiles(forced).allInnerTexts()
  await forced.getByRole('button', { name: /^Tools/ }).click()
  await expect(forced.getByText('The tool list is not available')).toBeVisible({ timeout: 30_000 })
  await shotTo(forced, path.join(laneDir(10), 'p7-runtime-down.png'), true)
  await forced.getByRole('button', { name: /^Agents/ }).click()
  await expect(tiles(forced), 'every tile has drawn again').toHaveCount(before.length)
  const after = await tiles(forced).allInnerTexts()
  save(10, 'p7-runtime-down.json', { realToolsStatus: realStatus, forced503: true, passesThrough: LANE_10_PASSES_THROUGH, tilesBefore: before, tilesAfter: after })
  expect(after.length, 'the cards stay').toBeGreaterThan(PLATFORM_AGENTS.length)
  expect(after).toEqual(before)
  await expect(forced.getByText('The tool list is not available')).toBeVisible()
  await context.close()
})

test('@perf largest contentful paint of the Agent library', async ({ browser }) => {
  onlyDev()
  test.skip(TARGET === 'trunk', 'trunk has no Agent library')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/agents', { waitUntil: 'load' })
  await expect(tiles(page).first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(2_000)
  const measured = await page.evaluate(
    () =>
      new Promise<{ entries: { startTime: number; size: number; element: string }[]; scripts: { name: string; transfer: number; encoded: number }[] }>((resolve) => {
        const entries: { startTime: number; size: number; element: string }[] = []
        const observer = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as (PerformanceEntry & { size: number; element: Element | null })[]) {
            const el = e.element
            entries.push({ startTime: e.startTime, size: e.size, element: el ? `${el.tagName.toLowerCase()} "${(el.textContent ?? '').trim().slice(0, 40)}"` : 'gone' })
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => {
          observer.disconnect()
          const scripts = (performance.getEntriesByType('resource') as PerformanceResourceTiming[])
            .filter((r) => r.initiatorType === 'script' || r.name.endsWith('.js'))
            .map((r) => ({ name: new URL(r.name).pathname, transfer: r.transferSize, encoded: r.encodedBodySize }))
          resolve({ entries, scripts })
        }, 500)
      }),
  )
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, lcp: last?.startTime ?? -1, element: last?.element ?? '', size: last?.size ?? 0, ...measured })
  await context.close()
})
