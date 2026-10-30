/**
 * The checker's own checks for P1's live lanes and perf block (docs/design/rebuild-plan.md).
 * Run through scripts/checks/p1.sh, which picks the stack and the lane with --grep @laneN.
 * Evidence goes to $EVID/lane-<n>/ with the file names the plan gives.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type BrowserContext, type Page, type Response } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p1'
const AUTH = process.env['E2E_AUTH'] ?? 'dev'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')

const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 }
const GREETING = (name: string) => new RegExp(`^Good (morning|afternoon|evening), ${name}$`)
const MENU = ['Home', 'Workflows', 'Software watchlist', 'Agent library'] as const
const PAGES = [
  { label: 'Home', path: '/', heading: GREETING('Alice') },
  { label: 'Workflows', path: '/workflows', heading: /^Workflows$/ },
  { label: 'Software watchlist', path: '/software', heading: /^Software watchlist$/ },
  { label: 'Agent library', path: '/agents', heading: /^Agent library$/ },
] as const
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function devContext(browser: Browser, user: string, { phone = false, mobile }: { phone?: boolean; mobile?: boolean } = {}): Promise<BrowserContext> {
  mobile ??= phone
  const context = await browser.newContext({
    viewport: phone ? PHONE : DESKTOP,
    ...(mobile ? { isMobile: true, hasTouch: true } : {}),
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
const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })

/** Waits until no animation is running, or 3 s, whichever is first. */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
}

async function shotTo(page: Page, file: string, fullPage = false): Promise<void> {
  await settle(page)
  mkdirSync(path.dirname(file), { recursive: true })
  await page.screenshot({ path: file, caret: 'hide', fullPage })
}

/** Lays shots out in a grid with a caption over each, and saves the result. */
async function composite(browser: Browser, shots: { label: string; file: string }[], out: string, columns: number, width = 720): Promise<void> {
  const context = await browser.newContext({ viewport: { width: columns * (width + 24) + 24, height: 600 } })
  const page = await context.newPage()
  const cells = shots
    .map(({ label, file }) => `<figure><figcaption>${label}</figcaption><img src="data:image/png;base64,${readFileSync(file).toString('base64')}"></figure>`)
    .join('')
  await page.setContent(
    `<style>body{margin:0;padding:12px;font:600 18px system-ui;background:#fff;display:grid;grid-template-columns:repeat(${columns},${width}px);gap:12px 24px}figure{margin:0}figcaption{padding:6px 0}img{width:${width}px;border:1px solid #888}</style>${cells}`,
  )
  await page.waitForFunction(() => [...document.images].every((img) => img.complete))
  await page.screenshot({ path: out, fullPage: true })
  await context.close()
}

function onlyDev(): void {
  test.skip(AUTH !== 'dev', 'needs dev sign-in')
}

// Lane 1. Old menu at trunk, new menu at head, both signed in as alice.
test('@lane1-capture sign in as alice and read the menu', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const apiCalls: { path: string; status: number; devUser: string | null; body: Promise<unknown> }[] = []
  page.on('response', (r) => {
    const { pathname } = new URL(r.url())
    if (pathname.startsWith('/api/')) apiCalls.push({ path: pathname, status: r.status(), devUser: r.request().headers()['x-dev-user'] ?? null, body: r.json().catch(() => null) as Promise<unknown> })
  })
  await page.goto('/')
  await expect(page.getByText('Alice').first(), 'the page names alice').toBeVisible()
  await expect.poll(() => apiCalls.some((c) => c.path === '/api/v1/me'), { message: 'the page asks GET /api/v1/me', timeout: 15_000 }).toBe(true).catch(() => undefined)
  const meCall = apiCalls.find((c) => c.path === '/api/v1/me')
  const me = { status: () => meCall?.status ?? -1 }
  const meBody = meCall ? await meCall.body : null
  const menu = (await mainMenu(page).first().getByRole('link').allInnerTexts()).map((label) => label.replace(/\s+/g, ' ').trim())
  const heading = (await page.locator('h1').first().innerText().catch(() => '')).trim()
  const file = path.join(laneDir(1), `p1-home-${TARGET}.png`)
  await shotTo(page, file)
  const record = { target: TARGET, url: page.url(), meStatus: me.status(), me: meBody, menu, heading, title: await page.title(), apiCalls: apiCalls.map(({ path: p, status, devUser }) => ({ path: p, status, devUser })) }
  save(1, `p1-home-${TARGET}.json`, record)
  expect(apiCalls.length, 'the page called the API').toBeGreaterThan(0)
  expect(apiCalls.filter((c) => c.status !== 200 || c.devUser !== 'alice').map((c) => `${c.path} ${c.status} as ${String(c.devUser)}`), 'every API call goes as alice and succeeds').toEqual([])
  await expect(page.getByRole('banner'), 'the header names alice').toContainText('Alice')
  if (TARGET === 'head') {
    expect(me.status(), 'GET /api/v1/me signs alice in').toBe(200)
    expect(meBody).toMatchObject({ id: 'alice', display: 'Alice' })
    expect(menu, 'head menu').toEqual([...MENU])
    expect(heading).toMatch(GREETING('Alice'))
    await expect(page.getByRole('banner')).toContainText('Alice')
    await expect(mainMenu(page).first().getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page')
  } else {
    expect(menu, 'trunk shows the old menu').toEqual(expect.arrayContaining(['Runs', 'Builder', 'Approvals']))
  }
  await context.close()
})

test('@lane1-combine side by side', async ({ browser }) => {
  onlyDev()
  const dir = laneDir(1)
  await composite(
    browser,
    [
      { label: `Trunk ${process.env['TRUNK_SHA'] ?? ''}, signed in as alice`.replace(' ,', ','), file: path.join(dir, 'p1-home-trunk.png') },
      { label: `Head ${process.env['HEAD_SHA'] ?? ''}, signed in as alice`.replace(' ,', ','), file: path.join(dir, 'p1-home-head.png') },
    ],
    path.join(dir, 'p1-home-trunk-head.png'),
    2,
  )
})

// Lane 3. Each menu item in turn: its own heading, and the URL changes.
test('@lane3 each menu item opens its own page at its own URL', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  await expect(h1(page)).toHaveText(GREETING('Alice'))
  const steps: { clicked: string; url: string; heading: string; title: string; current: string | null; notBuilt: boolean }[] = []
  const shots: { label: string; file: string }[] = []
  for (const item of [...PAGES.slice(1), PAGES[0]]) {
    const before = page.url()
    await mainMenu(page).getByRole('link', { name: item.label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${item.path === '/' ? '/' : item.path}$`))
    await expect(h1(page)).toHaveText(item.heading)
    const current = await mainMenu(page).locator('[aria-current="page"]').innerText().catch(() => null)
    steps.push({
      clicked: item.label,
      url: page.url(),
      heading: (await h1(page).innerText()).trim(),
      title: await page.title(),
      current,
      notBuilt: await page.getByRole('main').getByText('This page is not built yet.').isVisible(),
    })
    expect(page.url(), `${item.label} changes the URL`).not.toBe(before)
    expect(current, `${item.label} is marked as the current page`).toBe(item.label)
    const file = path.join(laneDir(3), `p1-menu-${item.label.toLowerCase().replaceAll(' ', '-')}.png`)
    await shotTo(page, file)
    shots.push({ label: `${item.label}: ${new URL(page.url()).pathname}`, file })
  }
  save(3, 'p1-menu-pages.json', steps)
  expect(new Set(steps.map((s) => s.url)).size, 'four different URLs').toBe(4)
  expect(new Set(steps.map((s) => s.heading)).size, 'four different headings').toBe(4)
  await composite(browser, shots, path.join(laneDir(3), 'p1-menu-pages.png'), 2)
  await context.close()
})

// Lane 4. Back and Forward across three pages.
test('@lane4 Back and Forward land on the page before and after', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const [home, workflows, software] = PAGES
  const steps: { step: string; url: string; heading: string; current: string | null; file: string }[] = []
  const record = async (step: string, expected: (typeof PAGES)[number]) => {
    await expect(page).toHaveURL(new RegExp(`${expected.path === '/' ? '/' : expected.path}$`))
    await expect(h1(page)).toHaveText(expected.heading)
    const current = await mainMenu(page).locator('[aria-current="page"]').innerText().catch(() => null)
    expect(current, `${step}: the menu marks ${expected.label}`).toBe(expected.label)
    const file = path.join(laneDir(4), `p1-back-forward-${steps.length + 1}.png`)
    await shotTo(page, file)
    steps.push({ step, url: new URL(page.url()).pathname, heading: (await h1(page).innerText()).trim(), current, file })
  }
  await page.goto('/')
  await record('load Home', home)
  await mainMenu(page).getByRole('link', { name: 'Workflows', exact: true }).click()
  await record('click Workflows', workflows)
  await mainMenu(page).getByRole('link', { name: 'Software watchlist', exact: true }).click()
  await record('click Software watchlist', software)
  await page.goBack()
  await record('Back', workflows)
  await page.goBack()
  await record('Back', home)
  await page.goForward()
  await record('Forward', workflows)
  await page.goForward()
  await record('Forward', software)
  save(4, 'p1-back-forward.json', steps)
  await composite(
    browser,
    steps.map((s, i) => ({ label: `${i + 1}. ${s.step} → ${s.url} "${s.heading}"`, file: s.file })),
    path.join(laneDir(4), 'p1-back-forward.png'),
    4,
    480,
  )
  await context.close()
})

// Lane 5. 390 px wide: the menu fits, nothing scrolls sideways, every item can be reached.
for (const mobile of [true, false]) {
  test(`@lane5 at 390 px the menu fits and every item can be reached (${mobile ? 'phone emulation' : 'narrow desktop window'})`, async ({ browser }) => {
    onlyDev()
    const context = await devContext(browser, 'alice', { phone: true, mobile })
    const page = await context.newPage()
    await page.goto('/')
    await expect(h1(page)).toHaveText(GREETING('Alice'))
    const mode = mobile ? 'phone' : 'narrow'
    if (mobile) await shotTo(page, path.join(laneDir(5), 'p1-phone.png'))
    else await shotTo(page, path.join(laneDir(5), 'p1-phone-narrow-desktop.png'))
    const bar = mainMenu(page)
    await expect(bar).toHaveCount(1)
    const labels = (await bar.getByRole('link').allInnerTexts()).map((t) => t.trim())
    const results: Record<string, unknown>[] = []
    const header = await page.getByRole('banner').evaluate((el) => {
      const out: { name: string; left: number; right: number; top: number; bottom: number }[] = []
      for (const node of el.querySelectorAll<HTMLElement>('a, button, [title]')) {
        const r = node.getBoundingClientRect()
        if (r.width > 0) out.push({ name: node.getAttribute('aria-label') ?? node.textContent.trim(), left: r.left, right: r.right, top: r.top, bottom: r.bottom })
      }
      return out
    })
    for (const control of header) expect(control.left >= 0 && control.right <= PHONE.width, `header control "${control.name}" fits in 390 px`).toBe(true)
    for (const [index, label] of labels.entries()) {
      const tab = bar.getByRole('link').nth(index)
      const box = await tab.boundingBox()
      expect(box, `${label} is laid out`).not.toBeNull()
      const fits = (box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= PHONE.width && (box?.y ?? -1) >= 0 && (box?.y ?? 0) + (box?.height ?? 0) <= PHONE.height
      const onTop = await tab.evaluate((el) => {
        const r = el.getBoundingClientRect()
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
        return hit !== null && el.contains(hit)
      })
      if (mobile) await tab.tap()
      else await tab.click()
      await expect(tab).toHaveAttribute('aria-current', 'page')
      const heading = (await h1(page).innerText()).trim()
      const widths = await page.evaluate(() => {
        const before = window.scrollX
        window.scrollBy(400, 0)
        const after = window.scrollX
        window.scrollTo(0, window.scrollY)
        return { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, bodyScroll: document.body.scrollWidth, before, after }
      })
      results.push({ label, box, fits, onTop, url: new URL(page.url()).pathname, heading, ...widths, tapTarget: box ? Math.min(box.width, box.height) : 0 })
      expect(fits, `${label} sits inside the 390 x 844 screen`).toBe(true)
      expect(onTop, `${label} is not covered by anything`).toBe(true)
      expect(widths.scrollWidth, `${label}: nothing scrolls sideways`).toBeLessThanOrEqual(widths.clientWidth)
      expect(widths.after, `${label}: a sideways scroll does not move the page`).toBe(0)
    }
    save(5, `p1-phone-${mode}.json`, { labels, header, results })
    expect(labels.length, 'four menu items').toBe(4)
    expect(results.map((r) => r['url']), 'every item opens its own page').toEqual(['/', '/workflows', '/software', '/agents'])
    // Settings and Teams in the header are reachable too.
    await page.getByRole('banner').getByRole('link', { name: 'Settings' }).click()
    await expect(h1(page)).toHaveText('Settings')
    await context.close()
  })
}

// Lane 6. Tab through the header: a visible focus ring on every control; the skip link moves focus to the heading.
test('@lane6 keyboard: focus rings in the header and the skip link', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  await expect(h1(page)).toHaveText(GREETING('Alice'))
  await settle(page)
  const headerControls = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('header a[href], header button, header [tabindex]:not([tabindex="-1"])')]
      .filter((el) => el.getBoundingClientRect().width > 0)
      .map((el) => el.getAttribute('aria-label') ?? el.textContent.trim().replace(/\s+/g, ' ').slice(0, 40)),
  )
  await page.evaluate(() => {
    ;(document.activeElement as HTMLElement | null)?.blur()
    window.scrollTo(0, 0)
  })
  const stops: { label: string; tag: string; inHeader: boolean; outline: string; shadow: string; pixelsChange: boolean; ringPx: number; crop: string }[] = []
  for (let press = 0; press < 30; press += 1) {
    await page.keyboard.press('Tab')
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        label: el.getAttribute('aria-label') ?? el.textContent.trim().replace(/\s+/g, ' ').slice(0, 40),
        tag: el.tagName.toLowerCase(),
        inHeader: el.closest('header') !== null,
        isSkip: el.textContent.trim() === 'Skip to main content',
        inMain: el.closest('main') !== null,
        outline: cs.outlineStyle === 'none' ? 'none' : `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor} offset ${cs.outlineOffset}`,
        ringPx: cs.outlineStyle === 'none' ? 0 : parseFloat(cs.outlineWidth),
        shadow: cs.boxShadow,
        box: { x: r.x, y: r.y, width: r.width, height: r.height },
      }
    })
    if (!info) break
    if (!info.inHeader && !info.isSkip) break
    const pad = 8
    const clip = { x: Math.max(0, info.box.x - pad), y: Math.max(0, info.box.y - pad), width: info.box.width + 2 * pad, height: info.box.height + 2 * pad }
    await page.waitForTimeout(250)
    const crop = path.join(laneDir(6), `focus-${stops.length + 1}.png`)
    const focused = await page.screenshot({ clip, path: crop })
    await page.evaluate(() => {
      const el = document.activeElement as HTMLElement & { e2eKeep?: boolean }
      ;(window as unknown as { kept: HTMLElement }).kept = el
      el.blur()
    })
    await page.waitForTimeout(250)
    const rest = await page.screenshot({ clip })
    await page.evaluate(() => (window as unknown as { kept: HTMLElement }).kept.focus({ preventScroll: true }))
    stops.push({ label: info.label, tag: info.tag, inHeader: info.inHeader, outline: info.outline, shadow: info.shadow, pixelsChange: !focused.equals(rest), ringPx: info.ringPx, crop })
  }
  const reached = stops.filter((s) => s.inHeader).map((s) => s.label)
  save(6, 'p1-keyboard.json', { headerControls, stops })
  await composite(
    browser,
    stops.map((s, i) => ({ label: `${i + 1}. ${s.label} (${s.outline})`, file: s.crop })),
    path.join(laneDir(6), 'p1-keyboard.png'),
    3,
    360,
  )
  expect(stops[0]?.label, 'the skip link is the first stop').toBe('Skip to main content')
  for (const control of headerControls) expect(reached, `Tab reaches "${control}"`).toContain(control)
  for (const stop of stops) {
    expect(stop.pixelsChange, `"${stop.label}" looks different when focused`).toBe(true)
    expect(stop.ringPx >= 2 || stop.shadow !== 'none', `"${stop.label}" draws a ring (outline ${stop.outline}, shadow ${stop.shadow})`).toBe(true)
  }

  // The skip link, by keyboard only, from a fresh load.
  await page.reload()
  await expect(h1(page)).toHaveText(GREETING('Alice'))
  await page.keyboard.press('Tab')
  const skip = page.getByRole('button', { name: 'Skip to main content' })
  await expect(skip).toBeFocused()
  const skipBox = await skip.boundingBox()
  expect(skipBox && skipBox.y >= 0 && skipBox.y + skipBox.height <= DESKTOP.height, 'the focused skip link is on the screen').toBe(true)
  await shotTo(page, path.join(laneDir(6), 'p1-keyboard-skip-link.png'))
  await page.keyboard.press('Enter')
  await expect(h1(page), 'Enter on the skip link moves focus to the page heading').toBeFocused()
  await page.keyboard.press('Tab')
  const after = await page.evaluate(() => ({ inHeader: document.activeElement?.closest('header') !== null, label: document.activeElement?.textContent.trim().slice(0, 40) }))
  save(6, 'p1-skip-link.json', { skipBox, afterSkipThenTab: after })
  expect(after.inHeader, 'Tab after the skip link goes on into the page, not back to the header').toBe(false)
  // The same on a second page, from a fresh load: the skip link goes to that page's heading.
  await mainMenu(page).getByRole('link', { name: 'Agent library', exact: true }).click()
  await expect(h1(page)).toHaveText('Agent library')
  await page.reload()
  await expect(h1(page)).toHaveText('Agent library')
  await page.keyboard.press('Tab')
  await expect(skip).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(h1(page)).toBeFocused()
  await context.close()
})

// Lane 7. axe, WCAG 2.2 AA tags, on four pages at 1440 and 390 px. Any violation fails.
test('@lane7 axe finds no WCAG 2.2 AA problem', async ({ browser }) => {
  onlyDev()
  const runs: Record<string, unknown>[] = []
  for (const [size, phone] of [
    ['1440', false],
    ['390', true],
  ] as const) {
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    for (const item of PAGES) {
      await page.goto(item.path)
      await expect(h1(page)).toHaveText(item.heading)
      await settle(page)
      const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
      runs.push({
        page: item.label,
        path: item.path,
        width: size,
        axe: result.testEngine.version,
        violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
        incomplete: result.incomplete.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
        passes: result.passes.length,
      })
    }
    await context.close()
  }
  const total = runs.reduce((sum, run) => sum + (run['violations'] as unknown[]).length, 0)
  save(7, 'p1-axe.json', { tags: WCAG_22_AA, totalViolations: total, runs })
  expect(
    runs.flatMap((run) => (run['violations'] as { id: string; impact: string }[]).map((v) => `${String(run['page'])} @${String(run['width'])}: ${v.id} (${v.impact})`)),
    'axe violations',
  ).toEqual([])
})

// Lane 8. bob, Approver only, opens the Settings gear.
test('@lane8 bob opens Settings from the gear', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const meResponse = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/v1/me')
  await page.goto('/')
  const me = await meResponse
  save(8, 'bob-me-from-page.json', { status: me.status(), body: (await me.json()) as unknown, sentDevUser: (await me.request().allHeaders())['x-dev-user'] })
  await expect(h1(page)).toHaveText(GREETING('Bob'))
  const banner = page.getByRole('banner')
  await expect(banner).toContainText('Bob')
  await expect(banner).toContainText('Approver')
  await expect(banner).not.toContainText('Operator')
  await banner.getByRole('link', { name: 'Settings' }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(h1(page)).toHaveText('Settings')
  await expect(page.getByRole('main')).toContainText('Only Operators change settings.')
  await expect(banner.getByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
  await shotTo(page, path.join(laneDir(8), 'p1-settings-approver.png'))
  save(8, 'p1-settings-approver.json', { url: page.url(), heading: await h1(page).innerText(), main: await page.getByRole('main').innerText(), banner: await banner.innerText() })
  // The other way in: Test controls, Act as Bob, from alice.
  const second = await devContext(browser, 'alice')
  const alice = await second.newPage()
  await alice.goto('/')
  await alice.getByRole('button', { name: 'Test controls' }).click()
  await alice.getByRole('region', { name: 'Test controls' }).getByRole('button', { name: 'Bob' }).click()
  await expect(h1(alice)).toHaveText(GREETING('Bob'))
  await alice.getByRole('banner').getByRole('link', { name: 'Settings' }).click()
  await expect(h1(alice)).toHaveText('Settings')
  await expect(alice.getByRole('main')).toContainText('Only Operators change settings.')
  await shotTo(alice, path.join(laneDir(8), 'p1-settings-approver-via-test-controls.png'))
  await second.close()
  await context.close()
})

// Lane 9. p1.sh stops the real platform-api before this runs, and starts it again when this writes .down-checked.
test('@lane9 the Portal says it cannot reach the platform, offers to try again, and recovers', async ({ browser }) => {
  onlyDev()
  const dir = laneDir(9)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const calls: { at: number; status: number; url: string }[] = []
  let start = 0
  page.on('response', (r: Response) => {
    if (new URL(r.url()).pathname.startsWith('/api/')) calls.push({ at: Date.now() - start, status: r.status(), url: new URL(r.url()).pathname })
  })
  page.on('requestfailed', (r) => calls.push({ at: Date.now() - start, status: -1, url: `${new URL(r.url()).pathname} ${r.failure()?.errorText ?? ''}` }))

  type State = 'blank' | 'empty-main' | 'loading' | 'message' | 'other' | 'navigating'
  const stateNow = (): Promise<State> =>
    page
      .evaluate((): State => {
        const main = document.querySelector('main')
        const text = main?.innerText.trim() ?? ''
        if (text.includes("We can't reach the platform")) return 'message'
        if (text === 'Loading') return 'loading'
        if (text === '') return document.body.innerText.trim() === '' ? 'blank' : 'empty-main'
        return 'other'
      })
      .catch((): State => 'navigating')
  /** Polls the page every 50 ms and returns each change of state with its time, until `until` holds or the time runs out. */
  const timeline = async (limitMs: number, until: (s: State) => boolean) => {
    const changes: { at: number; state: State }[] = []
    const t0 = Date.now()
    while (Date.now() - t0 < limitMs) {
      const state = await stateNow()
      if (changes.at(-1)?.state !== state) changes.push({ at: Date.now() - start, state })
      if (until(state)) break
      await page.waitForTimeout(50)
    }
    return changes
  }
  /** Blank before the bundle first draws is every single-page app; blank after it has drawn is the failure the lane looks for. */
  const blankAfterDrawn = (changes: { state: State }[]) => {
    const firstDrawn = changes.findIndex((c) => c.state !== 'blank' && c.state !== 'navigating')
    return firstDrawn >= 0 && changes.slice(firstDrawn).some((c) => c.state === 'blank')
  }

  start = Date.now()
  await page.goto('/', { waitUntil: 'commit' })
  const firstLoad = await timeline(180_000, (s) => s === 'message')
  await expect(page.getByRole('heading', { name: "We can't reach the platform" })).toBeVisible()
  const retry = page.getByRole('button', { name: 'Try again' })
  await expect(retry).toBeVisible()
  await expect(page.getByRole('main')).toContainText('Check your connection, or try again in a moment.')
  await expect(page.getByRole('banner')).toContainText('Workflow Builder')
  await expect(mainMenu(page).getByRole('link')).toHaveCount(4)
  const bodyText = await page.evaluate(() => document.body.innerText)
  await shotTo(page, path.join(dir, 'p1-api-down.png'))

  // Try again while it is still down: watch 5 s for the requests it makes and what the page shows meanwhile.
  start = Date.now()
  const callsBefore = calls.length
  await retry.click()
  const whileDown = await timeline(5_000, () => false)
  const retryCallsWhileDown = calls.slice(callsBefore)
  await expect(retry).toBeVisible()

  // A deep link while down shows the same message.
  start = Date.now()
  const callsBeforeDeep = calls.length
  await page.goto('/agents', { waitUntil: 'commit' })
  const deepLink = await timeline(180_000, (s) => s === 'message')
  const deepLinkCalls = calls.slice(callsBeforeDeep)
  await shotTo(page, path.join(dir, 'p1-api-down-deep-link.png'))

  writeFileSync(path.join(dir, '.down-checked'), String(Date.now()))
  await expect.poll(() => existsSync(path.join(dir, '.api-up')), { timeout: 150_000, intervals: [500], message: 'p1.sh starts platform-api again' }).toBe(true)

  start = Date.now()
  const callsBeforeUp = calls.length
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(h1(page)).toHaveText('Agent library', { timeout: 30_000 })
  const recoveredMs = Date.now() - start
  await shotTo(page, path.join(dir, 'p1-api-back.png'))

  // Baseline with the platform up, for the pre-draw blank frame.
  start = Date.now()
  await page.goto('/', { waitUntil: 'commit' })
  const healthyLoad = await timeline(30_000, (s) => s === 'other')

  const firstAt = (changes: { at: number; state: State }[], state: State) => changes.find((c) => c.state === state)?.at ?? null
  save(9, 'p1-api-down.json', {
    firstLoad,
    loadingShownMs: (firstAt(firstLoad, 'message') ?? 0) - (firstAt(firstLoad, 'loading') ?? 0),
    retryWhileDown: whileDown,
    retryCallsWhileDown,
    deepLink,
    deepLinkLoadingShownMs: (firstAt(deepLink, 'message') ?? 0) - (firstAt(deepLink, 'loading') ?? 0),
    deepLinkCalls,
    recoveredAfterTryAgainMs: recoveredMs,
    callsAfterUp: calls.slice(callsBeforeUp),
    healthyLoadForComparison: healthyLoad,
    bodyTextWhileDown: bodyText,
  })
  expect(blankAfterDrawn(firstLoad), 'once drawn, the page never goes blank on first load').toBe(false)
  expect(blankAfterDrawn(deepLink), 'once drawn, the page never goes blank on a deep link').toBe(false)
  expect(whileDown.some((c) => c.state === 'blank' || c.state === 'empty-main'), 'Try again never leaves a blank page').toBe(false)
  expect(firstLoad.at(-1)?.state).toBe('message')
  expect(deepLink.at(-1)?.state).toBe('message')
  await context.close()
})

// Lane 10. Retired names in every page's text, at both widths, with the panels open.
test('@lane10 no retired name in any page a person can see', async ({ browser }) => {
  onlyDev()
  const pages = [...PAGES.map((p) => p.path), '/settings', '/nowhere']
  const texts: { width: number; path: string; state: string; title: string; innerText: string; visibleText: string; attributes: string[] }[] = []
  const read = async (page: Page, width: number, where: string, state: string) =>
    texts.push({
      width,
      path: where,
      state,
      title: await page.title(),
      ...(await page.evaluate(() => {
        const hiddenByClip = (el: Element | null): boolean => {
          for (let node = el; node; node = node.parentElement) {
            const cs = getComputedStyle(node)
            const r = node.getBoundingClientRect()
            if (cs.display === 'none' || cs.visibility === 'hidden') return true
            if ((cs.clip !== 'auto' || cs.overflow === 'hidden') && r.width <= 1 && r.height <= 1) return true
          }
          return false
        }
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
        const visible: string[] = []
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const words = node.textContent?.trim() ?? ''
          if (words && !hiddenByClip(node.parentElement)) visible.push(node.textContent ?? '')
        }
        const attributes = [...document.querySelectorAll('[aria-label], [title], [alt], [placeholder], [aria-description]')].flatMap((el) =>
          ['aria-label', 'title', 'alt', 'placeholder', 'aria-description'].map((a) => el.getAttribute(a)).filter((v): v is string => Boolean(v)),
        )
        return { innerText: document.body.innerText, visibleText: visible.join('').replace(/\s+/g, ' '), attributes }
      })),
    })
  for (const phone of [false, true]) {
    const width = phone ? PHONE.width : DESKTOP.width
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    for (const where of pages) {
      await page.goto(where)
      await expect(h1(page)).toBeVisible()
      await read(page, width, where, 'loaded')
    }
    await page.goto('/')
    await expect(h1(page)).toBeVisible()
    await page.getByRole('button', { name: 'Test controls' }).click()
    await read(page, width, '/', 'test controls open')
    await page.getByRole('button', { name: 'Teams, practice copy' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await read(page, width, '/', 'Teams open')
    await context.close()
  }
  const retired: [string, RegExp][] = [
    ['Room lead', /room[\s_-]*lead/gi],
    ['Release checker', /release[\s_-]*check(er)?/gi],
    ['use case', /use[\s_-]*cases?/gi],
    ['Runs', /\bRuns\b/g],
    ['Approvals', /\bApprovals\b/g],
    ['old themed names', /\b(Flint|Forge|Striker|Spark Map|Scout|Analyst|Messenger|Clerk|Fixer|Kindling|Firebreak|Ember)\b/g],
  ]
  const lines: string[] = []
  const hits: string[] = []
  for (const t of texts) {
    const all = [t.title, t.innerText, t.attributes.join(' | ')].join(' || ').replace(/\s+/g, ' ')
    for (const [name, pattern] of retired) for (const m of all.matchAll(pattern)) hits.push(`${t.width}px ${t.path} (${t.state}): ${name}: "${all.slice(Math.max(0, (m.index ?? 0) - 40), (m.index ?? 0) + 40).replace(/\s+/g, ' ')}"`)
    for (const [label, source] of [
      ['innerText + title + attributes', all],
      ['visible text only', t.visibleText],
    ] as const) {
      for (const m of source.matchAll(/builder/gi)) {
        const at = m.index ?? 0
        const inName = source.slice(Math.max(0, at - 12), at + 7) === 'AI Workflow Builder'
        const line = `${t.width}px ${t.path} (${t.state}) [${label}]: "${source.slice(Math.max(0, at - 30), at + 20).replace(/\s+/g, ' ')}"${inName ? '' : '  <-- not inside "AI Workflow Builder"'}`
        lines.push(line)
      }
    }
  }
  save(10, 'page-text.json', texts)
  save(10, 'page-hits.txt', [`retired-name hits in page text: ${hits.length}`, ...hits, '', 'every "Builder" in page text:', ...lines, ''].join('\n'))
  expect(hits, 'retired names in page text').toEqual([])
  expect(
    lines.filter((l) => l.includes('[innerText') && l.endsWith('<-- not inside "AI Workflow Builder"')),
    'Builder outside the product name, in the text the page carries',
  ).toEqual([])
})

// Lane 2. Real sign-in through the mock identity provider.
test('@lane2 alice signs in through the mock identity provider and no X-Dev-User leaves the browser', async ({ browser }) => {
  test.skip(AUTH !== 'oidc', 'needs the oidc stack')
  const dir = laneDir(2)
  const context = await browser.newContext({ viewport: DESKTOP, locale: 'en-SG', timezoneId: 'Asia/Singapore' })
  const page = await context.newPage()
  const pending: Promise<{ url: string; method: string; devUser: string | null; bearer: boolean } | null>[] = []
  page.on('request', (r) => {
    pending.push(
      r
        .allHeaders()
        .then((h) => ({ url: r.url(), method: r.method(), devUser: h['x-dev-user'] ?? null, bearer: (h['authorization'] ?? '').startsWith('Bearer ') }))
        // A request still in flight when the page closes cannot be read, and it has nothing left to send.
        .catch(() => null),
    )
  })
  const meBodies: unknown[] = []
  page.on('response', (r) => {
    if (new URL(r.url()).pathname === '/api/v1/me') void r.json().then((b: unknown) => meBodies.push({ status: r.status(), body: b })).catch(() => undefined)
  })
  await page.goto('/')
  const username = page.locator('input[name="username"]')
  await expect(username, 'a signed-out person goes to the identity provider').toBeVisible({ timeout: 60_000 })
  await shotTo(page, path.join(dir, 'p1-oidc-provider-form.png'))
  await username.fill('alice')
  await page.locator('input[type="submit"]').click()
  await expect(page).toHaveURL(/:\/\/localhost:8080\/$/, { timeout: 30_000 })
  await expect(h1(page)).toHaveText(GREETING('Alice'))
  await expect(page.getByRole('banner')).toContainText('Alice')
  await expect(page.getByRole('banner')).toContainText('Operator and Approver')
  await expect(mainMenu(page).getByRole('link')).toHaveText([...MENU])
  await expect(page.getByRole('button', { name: /Test controls/ }), 'real sign-in hides the test controls').toHaveCount(0)
  await shotTo(page, path.join(dir, 'p1-oidc-sign-in.png'))
  for (const label of ['Workflows', 'Software watchlist', 'Agent library', 'Home']) {
    await mainMenu(page).getByRole('link', { name: label, exact: true }).click()
    await expect(h1(page)).toBeVisible()
  }
  await page.getByRole('banner').getByRole('link', { name: 'Settings' }).click()
  await expect(h1(page)).toHaveText('Settings')
  await page.reload()
  await expect(page.getByRole('banner')).toContainText('Alice')
  const requests = (await Promise.all(pending)).filter((r) => r !== null)
  const api = requests.filter((r) => new URL(r.url).pathname.startsWith('/api/'))
  save(2, 'p1-oidc-requests.json', { total: requests.length, api, withDevUser: requests.filter((r) => r.devUser !== null), me: meBodies })
  expect(requests.filter((r) => r.devUser !== null), 'requests that carry X-Dev-User').toEqual([])
  expect(api.length, 'the page called the API').toBeGreaterThan(0)
  expect(api.every((r) => r.bearer), 'every API call carries a bearer token').toBe(true)
  expect(meBodies[0], 'GET /api/v1/me answers for alice').toMatchObject({ status: 200, body: { display: 'Alice', roles: ['operator', 'approver'] } })
  await context.close()
})

// Perf. Largest contentful paint of Home after sign-in, one sample per run; p1.sh interleaves trunk and head.
test('@perf largest contentful paint of Home', async ({ browser }) => {
  onlyDev()
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/', { waitUntil: 'load' })
  await expect(page.locator('h1').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Alice').first()).toBeVisible()
  await page.waitForTimeout(2_000)
  const measured = await page.evaluate(
    () =>
      new Promise<{ entries: { startTime: number; size: number; element: string }[]; nav: Record<string, number>; scripts: { name: string; transfer: number; encoded: number }[] }>((resolve) => {
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
          const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
          const scripts = (performance.getEntriesByType('resource') as PerformanceResourceTiming[])
            .filter((r) => r.initiatorType === 'script' || r.name.endsWith('.js'))
            .map((r) => ({ name: new URL(r.name).pathname, transfer: r.transferSize, encoded: r.encodedBodySize }))
          resolve({ entries, nav: { domContentLoaded: nav.domContentLoadedEventEnd, load: nav.loadEventEnd, responseEnd: nav.responseEnd }, scripts })
        }, 500)
      }),
  )
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, lcp: last?.startTime ?? -1, element: last?.element ?? '', size: last?.size ?? 0, ...measured })
  await context.close()
})

// A walk-through for a person to watch: sign in, the menu, Teams, Test controls, Settings, then the phone width.
// Writes $EVID/p1-review.webm. Run with --grep @review-video.
test('@review-video alice walks the menu, Teams, Test controls and Settings, then the phone width', async ({ browser }) => {
  onlyDev()
  test.setTimeout(120_000)
  const pause = (page: Page, ms = 2500) => page.waitForTimeout(ms)
  const context = await browser.newContext({
    viewport: DESKTOP,
    recordVideo: { dir: path.join(EVID, '.review-video'), size: DESKTOP },
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
  await context.addInitScript(() => window.localStorage.setItem('portal.dev-user', 'alice'))
  const page = await context.newPage()
  const video = page.video()
  await page.goto('/')
  await expect(h1(page)).toHaveText(GREETING('Alice'))
  await pause(page, 2500)
  for (const label of MENU.slice(1)) {
    await mainMenu(page).first().getByRole('link', { name: label, exact: true }).click()
    await expect(mainMenu(page).first().getByRole('link', { name: label, exact: true })).toHaveAttribute('aria-current', 'page')
    await pause(page)
  }
  await mainMenu(page).first().getByRole('link', { name: 'Home', exact: true }).click()
  await pause(page)

  await page.getByRole('banner').getByRole('button', { name: /Teams/ }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await pause(page, 2500)
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()
  await pause(page, 1000)

  await page.getByRole('button', { name: 'Test controls' }).click()
  await pause(page, 2200)
  await page.getByRole('region', { name: 'Test controls' }).getByRole('button', { name: 'Bob' }).click()
  await expect(h1(page)).toHaveText(GREETING('Bob'))
  await pause(page, 2500)

  await page.getByRole('banner').getByRole('link', { name: 'Settings' }).click()
  await expect(h1(page)).toHaveText('Settings')
  await pause(page, 2500)

  await mainMenu(page).first().getByRole('link', { name: 'Home', exact: true }).click()
  await pause(page, 1000)
  await page.setViewportSize(PHONE)
  await expect(h1(page)).toHaveText(GREETING('Bob'))
  await pause(page, 2500)
  // The phone bar shortens some labels, so reach the items by position.
  for (const index of [1, 2, 3]) {
    await mainMenu(page).first().getByRole('link').nth(index).click()
    await pause(page, 2200)
  }
  await context.close()
  mkdirSync(EVID, { recursive: true })
  await video?.saveAs(path.join(EVID, 'p1-review.webm'))
})
