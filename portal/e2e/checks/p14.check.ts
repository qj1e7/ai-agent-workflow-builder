import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { openSettings, personRow, roleBox } from '../live/support/settings'
import { assertClean, watchPage, type Watch } from '../support/test'

// The checker's lanes for P14, after the operator's deploy. scripts/checks/p14.sh runs them on the host, not in the
// runner image, because Azure signs people in through Entra ID. Every address comes from a setting: AZURE_PORTAL_URL
// and LOCAL_PORTAL_URL. The saved sign-ins are in P14_STATE_DIR, made by `p14.sh signin`. Nothing here holds a
// secret: an access token never leaves the page that signed in, and a model key is typed by the operator.

const EVID = process.env['EVID'] ?? '/tmp/swarm-p14'
const AZURE = (process.env['AZURE_PORTAL_URL'] ?? '').replace(/\/+$/, '')
const LOCAL = (process.env['LOCAL_PORTAL_URL'] ?? 'http://localhost:8080').replace(/\/+$/, '')
const STATE_DIR = process.env['P14_STATE_DIR'] ?? ''
const SIGNIN = process.env['P14_SIGNIN'] ?? ''
const SAMPLES = Number(process.env['P14_SAMPLES'] ?? '5')
const FOR_A_PERSON_MS = 10 * 60_000
const ASK_HEADING = 'Ask an Operator to add you'
const DESKTOP = { width: 1440, height: 900 }

type Who = 'operator' | 'approver' | 'outsider'
const DEV_USER: Record<Who, string> = { operator: 'alice', approver: 'bob', outsider: 'nobody' }

interface Target {
  readonly name: 'azure' | 'local'
  readonly base: string
}

const AZURE_TARGET: Target = { name: 'azure', base: AZURE }
const LOCAL_TARGET: Target = { name: 'local', base: LOCAL }

interface Software {
  readonly name: string
  readonly repo: string
  readonly our_version: string
}

// Each lane watches its own repository at an old version, so its check always proposes a ticket and stops at the
// approval gate, whatever else is on the list.
const SOFTWARE = {
  lane1: { name: 'FastAPI', repo: 'fastapi/fastapi', our_version: '0.100.0' },
  lane4: { name: 'Pydantic', repo: 'pydantic/pydantic', our_version: '2.0.0' },
  lane8: { name: 'HTTPX', repo: 'encode/httpx', our_version: '0.20.0' },
  perf: { name: 'Requests', repo: 'psf/requests', our_version: '2.20.0' },
} satisfies Record<string, Software>

interface Person {
  readonly target: Target
  readonly who: Who
  readonly context: BrowserContext
  readonly page: Page
  readonly watch: Watch
}

interface Answer<T> {
  readonly status: number
  readonly body: T
}

interface RunEvent {
  readonly run_id: string
  readonly seq: number
  readonly ts: string
  readonly kind: string
  readonly summary: string
  readonly data: Record<string, unknown>
}

interface StreamFrame {
  readonly seq: number
  readonly kind: string
  readonly ts: string
  readonly at: number
  readonly stream: number
}

interface StreamOpen {
  readonly url: string
  readonly opened: number
}

interface Probe {
  readonly streams: StreamOpen[]
  readonly frames: StreamFrame[]
  lcp: number
}

function laneDir(lane: string): string {
  const dir = path.join(EVID, lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function shot(page: Page, lane: string, name: string, fullPage = false): Promise<string> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running'), undefined, { timeout: 5_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  const file = path.join(laneDir(lane), name)
  await page.screenshot({ path: file, caret: 'hide', fullPage })
  return file
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })

function needAzure(): void {
  if (!/^https:\/\/[^/]+$/.test(AZURE)) throw new Error('Set AZURE_PORTAL_URL to the Portal address that deploy.yml printed, such as https://portal.<domain>.')
}

function statePath(who: Who): string {
  if (!STATE_DIR) throw new Error('Set P14_STATE_DIR to the folder that `scripts/checks/p14.sh signin` saved the sign-ins in.')
  return path.join(STATE_DIR, `${who}.json`)
}

// Records each event as it arrives on the run page's stream, and Home's largest contentful paint. The page reads the
// stream with fetch, so the script reads a copy of each stream body beside it and leaves the page's own copy alone.
function installProbe(): void {
  const probe: Probe = { streams: [], frames: [], lcp: 0 }
  Object.assign(window, { __p14: probe })
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) probe.lcp = entry.startTime
  }).observe({ type: 'largest-contentful-paint', buffered: true })
  const realFetch = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const response = await realFetch(input, init)
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const body = response.body
    if (!/\/api\/v1\/runs\/[^/]+\/events/.test(url) || !(response.headers.get('content-type') ?? '').includes('text/event-stream') || !body) return response
    const stream = probe.streams.push({ url, opened: Date.now() }) - 1
    const [mine, theirs] = body.tee()
    void (async () => {
      const reader = mine.getReader()
      const decoder = new TextDecoder()
      let rest = ''
      for (;;) {
        const chunk = await reader.read().catch(() => null)
        if (!chunk || chunk.done) return
        const at = Date.now()
        rest += decoder.decode(chunk.value, { stream: true })
        const lines = rest.split(/\r\n|\r|\n/)
        rest = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const event = JSON.parse(line.slice(5).trim()) as { seq?: unknown; kind?: unknown; ts?: unknown }
            if (typeof event.seq === 'number' && typeof event.ts === 'string') probe.frames.push({ seq: event.seq, kind: String(event.kind), ts: event.ts, at, stream })
          } catch {
            // A frame that is not an event, such as a keep-alive, is not timed.
          }
        }
      }
    })()
    return new Response(theirs, { status: response.status, statusText: response.statusText, headers: response.headers })
  }
}

async function probeOf(page: Page): Promise<Probe> {
  return page.evaluate(() => (window as unknown as { __p14: Probe }).__p14)
}

async function newContext(browser: Browser, target: Target, who: Who, extra: { fresh?: boolean } = {}): Promise<BrowserContext> {
  const signedIn = target.name === 'azure' && !extra.fresh
  if (signedIn && !existsSync(statePath(who))) throw new Error(`No saved sign-in for ${who}. Run scripts/checks/p14.sh signin ${who} first.`)
  const context = await browser.newContext({
    baseURL: target.base,
    viewport: DESKTOP,
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
    ...(signedIn ? { storageState: statePath(who) } : {}),
  })
  if (target.name === 'local') {
    await context.addInitScript((id) => {
      try {
        window.localStorage.setItem('portal.dev-user', id)
      } catch {
        // A page without storage signs in as the default person.
      }
    }, DEV_USER[who])
  }
  await context.addInitScript(installProbe)
  return context
}

/** Opens Home as `who`. On Azure the saved sign-in carries Entra ID's cookies, so the Portal's sign-in comes back on its own. */
async function open(browser: Browser, target: Target, who: Who): Promise<Person> {
  if (target.name === 'azure') needAzure()
  const context = await newContext(browser, target, who)
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/')
  await landed(page, target, who)
  return { target, who, context, page, watch }
}

/** Waits until the page is back on the Portal with a heading. On Azure it also waits for the Portal to hold its sign-in,
 * because Entra ID's own sign-in page has a level-one heading too. */
async function landed(page: Page, target: Target, who: Who, timeout = 90_000): Promise<void> {
  const origin = new URL(target.base).origin
  const ready = async (): Promise<boolean> => {
    const url = new URL(page.url())
    if (url.origin !== origin || url.pathname === '/auth/callback') return false
    if (target.name === 'azure') {
      const signedIn = await page.evaluate(() => Object.keys(window.sessionStorage).some((name) => name.startsWith('oidc.user:'))).catch(() => false)
      if (!signedIn) return false
    }
    return h1(page).isVisible()
  }
  try {
    await expect.poll(ready, { message: `the Portal signs ${who} in on ${target.name}`, timeout, intervals: [500] }).toBe(true)
  } catch (error) {
    if (target.name === 'azure' && new URL(page.url()).origin !== origin) {
      throw new Error(`The saved sign-in for ${who} no longer signs in on its own (the page is at ${new URL(page.url()).host}). Run scripts/checks/p14.sh signin ${who} again.`, { cause: error })
    }
    throw error
  }
}

/** Calls the API through the Portal, inside the page, so a token never leaves the browser. */
async function call<T>(person: Person, method: string, apiPath: string, body?: unknown, headers: Record<string, string> = {}): Promise<Answer<T>> {
  const answer = await person.page.evaluate(
    async ({ method, apiPath, body, headers, devUser }) => {
      const sent: Record<string, string> = { Accept: 'application/json', ...headers }
      if (devUser) {
        sent['X-Dev-User'] = devUser
      } else {
        const key = Object.keys(window.sessionStorage).find((name) => name.startsWith('oidc.user:'))
        const user = key ? (JSON.parse(window.sessionStorage.getItem(key) ?? '{}') as { access_token?: string }) : {}
        if (!user.access_token) throw new Error('The page holds no access token. Is this person signed in?')
        sent['Authorization'] = `Bearer ${user.access_token}`
      }
      if (body !== undefined) sent['Content-Type'] = 'application/json'
      const response = await fetch(apiPath, { method, headers: sent, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
      return { status: response.status, text: await response.text() }
    },
    { method, apiPath, body, headers, devUser: person.target.name === 'local' ? DEV_USER[person.who] : null },
  )
  return { status: answer.status, body: (answer.text ? JSON.parse(answer.text) : null) as T }
}

async function get<T>(person: Person, apiPath: string): Promise<T> {
  const answer = await call<T>(person, 'GET', apiPath)
  expect(answer.status, `GET ${apiPath} as ${person.who} on ${person.target.name}`).toBe(200)
  return answer.body
}

/** Puts the lane's software on the watchlist afresh and starts a check of the list. Answers the run's id. */
async function startCheck(person: Person, software: Software): Promise<string> {
  const { watchlist } = await get<{ watchlist: { software: { id: string; source: { ref: string } }[] } | null }>(person, '/api/v1/watchlist')
  for (const item of watchlist?.software ?? []) {
    if (item.source.ref.toLowerCase() === software.repo.toLowerCase()) {
      const removed = await call(person, 'DELETE', `/api/v1/watchlist/software/${item.id}`)
      expect(removed.status, `remove the old ${software.name}`).toBe(200)
    }
  }
  const added = await call<{ use_case_id: string }>(person, 'POST', '/api/v1/watchlist/software', software)
  expect(added.status, `add ${software.name}: ${JSON.stringify(added.body)}`).toBe(201)
  const started = await call<{ run_id: string }>(person, 'POST', `/api/v1/use-cases/${added.body.use_case_id}/runs`, undefined, { 'Idempotency-Key': randomUUID() })
  expect(started.status, `start the check: ${JSON.stringify(started.body)}`).toBe(201)
  return started.body.run_id
}

async function eventsOf(person: Person, runId: string): Promise<RunEvent[]> {
  const all: RunEvent[] = []
  for (let page = 0; page < 50; page += 1) {
    const after = all.at(-1)?.seq ?? 0
    const { events } = await get<{ events: RunEvent[] }>(person, `/api/v1/runs/${runId}/events?after=${after}`)
    const fresh = events.filter((event) => event.seq > after)
    if (fresh.length === 0) return all
    all.push(...fresh)
  }
  return all
}

async function stateOf(person: Person, runId: string): Promise<string> {
  return (await get<{ state: string }>(person, `/api/v1/runs/${runId}`)).state
}

async function waitForState(person: Person, runId: string, wanted: readonly string[], timeout = 240_000): Promise<void> {
  await expect
    .poll(
      async () => {
        const state = await stateOf(person, runId)
        if (!wanted.includes(state) && ['succeeded', 'rejected', 'failed'].includes(state)) throw new Error(`run ${runId} ended as ${state}, wanted ${wanted.join(' or ')}`)
        return wanted.includes(state)
      },
      { message: `run ${runId} on ${person.target.name} reaches ${wanted.join(' or ')}`, timeout, intervals: [1_000] },
    )
    .toBe(true)
}

/** The kinds in the order they first appear, up to the approval request, so a longer watchlist reads the same. */
function stagesToGate(events: readonly RunEvent[]): string[] {
  const stages: string[] = []
  for (const event of events) {
    if (!stages.includes(event.kind)) stages.push(event.kind)
    if (event.kind === 'approval_requested') break
  }
  return stages
}

/** Each station's state and label, without its small line, which says how long ago and so differs between runs. */
async function stations(page: Page): Promise<string[]> {
  return page.locator('ol[aria-label="Steps of this run"] > li[data-state]').evaluateAll((items) =>
    items.map((li) => {
      const label = li.lastElementChild?.cloneNode(true)
      if (label instanceof Element) for (const small of label.querySelectorAll('small')) small.remove()
      return `${li.getAttribute('data-state') ?? ''}: ${(label?.textContent ?? '').replace(/\s+/g, ' ').trim()}`
    }),
  )
}

async function chatLines(page: Page): Promise<string[]> {
  return page.locator('ol[aria-label="What the agents said"] > li').evaluateAll((items) => items.map((li) => (li.textContent ?? '').replace(/\s+/g, ' ').trim()))
}

async function besideEachOther(browser: Browser, lane: string, name: string, shots: readonly { caption: string; file: string }[]): Promise<void> {
  const page = await browser.newPage({ viewport: { width: 2 * DESKTOP.width + 48, height: DESKTOP.height + 64 } })
  const figures = shots
    .map(({ caption, file }) => `<figure><figcaption>${caption}</figcaption><img src="data:image/png;base64,${readFileSync(file).toString('base64')}"></figure>`)
    .join('')
  await page.setContent(
    `<style>body{margin:16px;display:flex;gap:16px;font:16px system-ui;background:#fff}figure{margin:0}img{width:${DESKTOP.width}px;border:1px solid #ccc}</style>${figures}`,
  )
  await page.screenshot({ path: path.join(laneDir(lane), name), fullPage: true })
  await page.close()
}

function percentile(values: readonly number[], share: number): number {
  const ordered = [...values].sort((a, b) => a - b)
  return ordered[Math.max(0, Math.ceil(share * ordered.length) - 1)] ?? Number.NaN
}

function median(values: readonly number[]): number {
  return percentile(values, 0.5)
}

test('signs in once as the test account for P14_SIGNIN and saves the browser state for the lanes @signin', async ({ browser }) => {
  test.skip(!SIGNIN, 'run through scripts/checks/p14.sh signin <who>')
  test.setTimeout(FOR_A_PERSON_MS + 60_000)
  needAzure()
  const who = SIGNIN as Who
  expect(['operator', 'approver', 'outsider'], 'P14_SIGNIN names who signs in').toContain(who)
  const context = await newContext(browser, AZURE_TARGET, who, { fresh: true })
  const page = await context.newPage()
  await page.goto('/')
  console.log(`Sign in as the ${who} test account in the browser window. Answer Yes to "Stay signed in?". The window closes once the Portal shows a page.`)
  await landed(page, AZURE_TARGET, who, FOR_A_PERSON_MS)
  if (who === 'outsider') await expect(h1(page), 'the outsider is not on the People list').toHaveText(ASK_HEADING)
  else await expect(h1(page), `the ${who} is on the People list`).not.toHaveText(ASK_HEADING)
  mkdirSync(STATE_DIR, { recursive: true, mode: 0o700 })
  const file = statePath(who)
  const state = await context.storageState()
  writeFileSync(file, JSON.stringify(state), { mode: 0o600 })
  chmodSync(file, 0o600)
  const entra = state.cookies.filter((cookie) => cookie.domain.endsWith('login.microsoftonline.com')).length
  expect(entra, 'the saved state holds Entra ID cookies, so the lanes can sign in without a person').toBeGreaterThan(0)
  console.log(`Saved the ${who} sign-in in ${file}: ${state.cookies.length} cookies, ${entra} of them Entra ID's. Never commit this file.`)
  await context.close()
})

test('lane 1: a watchlist check reaches the approval gate with the same steps on the local stack at head and on Azure @lane1', async ({ browser }) => {
  test.setTimeout(12 * 60_000)
  needAzure()
  const seen: Record<string, { runId: string; stages: string[]; stations: string[] }> = {}
  const shots: { caption: string; file: string }[] = []
  for (const target of [LOCAL_TARGET, AZURE_TARGET]) {
    const operator = await open(browser, target, 'operator')
    const runId = await startCheck(operator, SOFTWARE.lane1)
    await waitForState(operator, runId, ['awaiting_approval'])
    await operator.page.goto(`/runs/${runId}`)
    await expect(h1(operator.page)).toHaveText(/waiting for a yes$/, { timeout: 60_000 })
    shots.push({ caption: target.name === 'local' ? `Local stack at head (${LOCAL})` : 'Azure', file: await shot(operator.page, 'lane-1', `p14-${target.name}-gate.png`) })
    seen[target.name] = { runId, stages: stagesToGate(await eventsOf(operator, runId)), stations: await stations(operator.page) }
    assertClean(operator.watch)
    await operator.context.close()
  }
  await besideEachOther(browser, 'lane-1', 'p14-local-azure.png', shots)
  save('lane-1', 'p14-lane1.json', { trunk: 'Trunk was never deployed with these modules, so the local stack at head stands in for it.', ...seen })
  expect(seen['azure']?.stages, 'the same steps to the approval gate on Azure as on the local stack').toEqual(seen['local']?.stages)
  expect(seen['azure']?.stations, 'the same stations on the run page').toEqual(seen['local']?.stations)
})

test('lane 2: the first Operator signs in with Entra ID, Home names them and Settings shows them as Operator @lane2', async ({ browser }) => {
  const operator = await open(browser, AZURE_TARGET, 'operator')
  const me = await get<{ id: string; display: string; roles: string[]; on_list: boolean }>(operator, '/api/v1/me')
  expect(me.on_list, 'the first Operator is on the People list').toBe(true)
  expect(me.roles, 'with the Operator role').toContain('operator')
  const { people } = await get<{ people: { id: string; display: string; email: string; operator: boolean; approver: boolean }[] }>(operator, '/api/v1/people')
  const person = people.find((p) => p.id === me.id)
  expect(person, 'the People list holds the signed-in person').toBeDefined()
  await expect(h1(operator.page)).toHaveText(/^Good (morning|afternoon|evening), /)
  await expect(h1(operator.page), 'Home names the person').toContainText(me.display.split(' ')[0] ?? me.display)
  await expect(operator.page.getByRole('banner')).toContainText('Operator')
  await shot(operator.page, 'lane-2', 'p14-sign-in.png')
  await openSettings(operator.page, 'people')
  const row = personRow(operator.page, person?.email ?? '')
  await expect(row).toBeVisible()
  await expect(roleBox(operator.page, 'Operator', person?.display ?? ''), 'Settings shows them as Operator').toBeChecked()
  await shot(operator.page, 'lane-2', 'p14-sign-in-settings.png')
  save('lane-2', 'p14-sign-in.json', { me, person })
  assertClean(operator.watch)
  await operator.context.close()
})

test('lane 4: the first Operator runs a watchlist check, a first Approver approves it on the run page, and the practice Jira holds the ticket @lane4', async ({ browser }) => {
  test.setTimeout(10 * 60_000)
  const operator = await open(browser, AZURE_TARGET, 'operator')
  const approver = await open(browser, AZURE_TARGET, 'approver')
  const runId = await startCheck(operator, SOFTWARE.lane4)
  await operator.page.goto(`/runs/${runId}`)
  await waitForState(operator, runId, ['awaiting_approval'])
  await approver.page.goto(`/runs/${runId}`)
  await expect(h1(approver.page)).toHaveText(/waiting for a yes$/, { timeout: 60_000 })
  const approve = approver.page.getByRole('button', { name: /^Approve/ })
  await expect(approve, 'a first Approver who did not start the run may approve it').toBeVisible()
  await approve.click()
  await waitForState(operator, runId, ['succeeded'])
  await expect(h1(approver.page)).toHaveText(/created in Jira$/, { timeout: 60_000 })
  await shot(approver.page, 'lane-4', 'p14-approved.png')
  const { tickets } = await get<{ tickets: { key: string; run_id: string | null; title: string; status: string }[] }>(operator, '/api/v1/mock-jira/tickets')
  const mine = tickets.filter((ticket) => ticket.run_id === runId)
  save('lane-4', 'run.json', { run_id: runId, state: await stateOf(operator, runId), tickets: mine })
  expect(mine.length, 'the practice Jira holds the ticket this run wrote').toBeGreaterThan(0)
  expect(mine.map((ticket) => ticket.title).join(' | ')).toContain(SOFTWARE.lane4.name)
  for (const person of [operator, approver]) {
    assertClean(person.watch)
    await person.context.close()
  }
})

test("lane 5: reads lane 4's run events from the API, for p14.sh to compare with the Cosmos DB items @lane5", async ({ browser }) => {
  const file = path.join(laneDir('lane-4'), 'run.json')
  if (!existsSync(file)) throw new Error(`No ${file}. Run lane 4 first.`)
  const { run_id: runId } = JSON.parse(readFileSync(file, 'utf8')) as { run_id: string }
  const operator = await open(browser, AZURE_TARGET, 'operator')
  const events = await eventsOf(operator, runId)
  expect(events.length, 'the API answers the run events').toBeGreaterThan(0)
  save('lane-5', 'api-events.json', { run_id: runId, events: events.map(({ seq, kind, ts }) => ({ seq, kind, ts })) })
  await operator.context.close()
})

test('lane 6: the operator connects Claude Haiku 5.5 through the gateway in Settings, and Test and save succeeds @lane6', async ({ browser }) => {
  test.setTimeout(FOR_A_PERSON_MS + 2 * 60_000)
  const operator = await open(browser, AZURE_TARGET, 'operator')
  const before = await get<{ available: boolean; active: { at: string } | null; unavailable_message?: string | null }>(operator, '/api/v1/settings/model')
  expect(before.available, `Settings are on, so SETTINGS_ENCRYPTION_KEY is set: ${before.unavailable_message ?? ''}`).toBe(true)
  await openSettings(operator.page, 'model')
  console.log('In the browser window: pick AI Singapore gateway, paste the gateway key, press Connect, choose Claude Haiku 5.5, then press Test and save. The key goes from your keyboard to the page only.')
  await expect
    .poll(async () => (await get<{ active: { at: string } | null }>(operator, '/api/v1/settings/model')).active?.at ?? before.active?.at ?? '', {
      message: 'a new model is saved within 10 minutes',
      timeout: FOR_A_PERSON_MS,
      intervals: [3_000],
    })
    .not.toBe(before.active?.at ?? '')
  await expect(operator.page.getByRole('button', { name: 'Connect', exact: true }), 'the form is back at Connect once saved').toBeVisible({ timeout: 30_000 })
  const after = await get<{ active: { provider: string; model: string; key_hint: string; at: string } | null }>(operator, '/api/v1/settings/model')
  expect(after.active?.model ?? '', 'the saved model').toMatch(/haiku/i)
  await shot(operator.page, 'lane-6', 'p14-model.png')
  save('lane-6', 'p14-model.json', { provider: after.active?.provider, model: after.active?.model, saved_at: after.active?.at })
  assertClean(operator.watch)
  await operator.context.close()
})

test('lane 8: the run page reconnects after platform-api restarts during an open stream, and shows every event once @lane8', async ({ browser }) => {
  test.setTimeout(FOR_A_PERSON_MS + 8 * 60_000)
  const flags = laneDir('lane-8')
  const operator = await open(browser, AZURE_TARGET, 'operator')
  const approver = await open(browser, AZURE_TARGET, 'approver')
  const runId = await startCheck(operator, SOFTWARE.lane8)
  await waitForState(operator, runId, ['awaiting_approval'])
  await operator.page.goto(`/runs/${runId}`)
  await expect(h1(operator.page)).toHaveText(/waiting for a yes$/, { timeout: 60_000 })
  await expect.poll(async () => (await probeOf(operator.page)).streams.length, { message: 'the run page has its stream open', timeout: 30_000 }).toBeGreaterThan(0)
  const streamsBefore = (await probeOf(operator.page)).streams.length
  writeFileSync(path.join(flags, 'stream-open'), runId)
  console.log('The stream is open. p14.sh restarts platform-api now.')
  await expect.poll(() => existsSync(path.join(flags, 'restarted')), { message: 'p14.sh says platform-api restarted', timeout: FOR_A_PERSON_MS, intervals: [2_000] }).toBe(true)
  await expect
    .poll(async () => (await probeOf(operator.page)).streams.length, { message: 'the run page opens a new stream after the restart', timeout: 5 * 60_000, intervals: [2_000] })
    .toBeGreaterThan(streamsBefore)
  await approver.page.goto(`/runs/${runId}`)
  await approver.page.getByRole('button', { name: /^Approve/ }).click()
  await waitForState(approver, runId, ['succeeded'])
  await expect(h1(operator.page), 'the open page shows the run finishing').toHaveText(/created in Jira$/, { timeout: 120_000 })
  await shot(operator.page, 'lane-8', 'p14-restart.png', true)
  const live = await chatLines(operator.page)
  const probe = await probeOf(operator.page)
  const fresh = await operator.context.newPage()
  await fresh.goto(`/runs/${runId}`)
  await expect(h1(fresh)).toHaveText(/created in Jira$/, { timeout: 60_000 })
  const reloaded = await chatLines(fresh)
  const all = await eventsOf(operator, runId)
  const seqs = probe.frames.map((frame) => frame.seq)
  save('lane-8', 'p14-restart.json', {
    run_id: runId,
    events_in_the_api: all.length,
    streams: probe.streams,
    frames: probe.frames.map(({ seq, kind, stream }) => ({ seq, kind, stream })),
    frames_sent_twice: seqs.filter((seq, i) => seqs.indexOf(seq) !== i),
    live,
    reloaded,
  })
  expect(probe.streams.length, 'the page reconnected at least once').toBeGreaterThan(streamsBefore)
  expect(live, 'the open page shows each event once, as a fresh load of the run does').toEqual(reloaded)
  for (const person of [operator, approver]) {
    assertClean(person.watch)
    await person.context.close()
  }
})

test('lane 9: someone who is not on the People list is told to ask an Operator @lane9', async ({ browser }) => {
  const outsider = await open(browser, AZURE_TARGET, 'outsider')
  await expect(h1(outsider.page)).toHaveText(ASK_HEADING)
  const me = await get<{ on_list: boolean; roles: string[] }>(outsider, '/api/v1/me')
  expect(me, 'platform-api agrees the person is not on the list and has no role').toMatchObject({ on_list: false, roles: [] })
  const runs = await call(outsider, 'GET', '/api/v1/runs')
  save('lane-9', 'p14-not-on-list.json', { me, runs_status: runs.status })
  expect(runs.status, 'and refuses them the runs').toBe(403)
  await shot(outsider.page, 'lane-9', 'p14-not-on-list.png')
  assertClean(outsider.watch)
  await outsider.context.close()
})

test("perf: Home's largest contentful paint and the run page's event delay, on the local stack and on Azure, interleaved @perf", async ({ browser }) => {
  test.setTimeout(20 * 60_000)
  needAzure()
  const targets = [LOCAL_TARGET, AZURE_TARGET]
  const people = new Map<string, Person>()
  for (const target of targets) people.set(target.name, await open(browser, target, 'operator'))
  const paints: Record<string, number[]> = { local: [], azure: [] }
  for (let sample = 0; sample < SAMPLES; sample += 1) {
    for (const target of targets) {
      const person = people.get(target.name)
      if (!person) continue
      await person.page.goto('/')
      await expect(h1(person.page)).toHaveText(/^Good (morning|afternoon|evening), /, { timeout: 60_000 })
      await person.page.waitForLoadState('networkidle').catch(() => undefined)
      await sleep(1_000)
      paints[target.name]?.push(Math.round((await probeOf(person.page)).lcp))
    }
  }
  const delays: Record<string, number[]> = { local: [], azure: [] }
  const runs: Record<string, string> = {}
  for (const target of targets) {
    const person = people.get(target.name)
    if (!person) continue
    await person.page.goto('/')
    await landed(person.page, target, 'operator')
    const runId = await startCheck(person, SOFTWARE.perf)
    runs[target.name] = runId
    await person.page.goto(`/runs/${runId}`)
    await waitForState(person, runId, ['awaiting_approval'])
    await sleep(3_000)
    const probe = await probeOf(person.page)
    const opened = probe.streams[0]?.opened ?? Number.POSITIVE_INFINITY
    // Only events made after the stream opened arrive live. The ones before it come in the first replay.
    delays[target.name] = probe.frames.filter((frame) => Date.parse(frame.ts) >= opened).map((frame) => frame.at - Date.parse(frame.ts))
  }
  const result = Object.fromEntries(
    targets.map(({ name }) => [
      name,
      {
        home_lcp_ms: paints[name],
        home_lcp_median_ms: median(paints[name] ?? []),
        run_id: runs[name],
        live_events: delays[name]?.length ?? 0,
        event_delay_p50_ms: percentile(delays[name] ?? [], 0.5),
        event_delay_p95_ms: percentile(delays[name] ?? [], 0.95),
        event_delay_max_ms: percentile(delays[name] ?? [], 1),
      },
    ]),
  )
  save('perf', 'p14-perf.json', {
    method: "Largest contentful paint from the page's own PerformanceObserver, Home loaded once to sign in and warm up, then interleaved. Event delay as scripts/p95.py --stream reads it: the moment an event arrived on the run page's stream minus its ts, for events made after the stream opened. The browser's clock and Azure's both follow NTP, so a small skew stays in the Azure numbers.",
    samples: SAMPLES,
    ...result,
  })
  for (const person of people.values()) await person.context.close()
  const onAzure = result['azure'] as { home_lcp_median_ms: number; event_delay_p95_ms: number; live_events: number }
  expect(onAzure.live_events, 'the check streamed live events to time').toBeGreaterThan(0)
  expect(onAzure.home_lcp_median_ms, "Home's median largest contentful paint on Azure").toBeLessThan(3_000)
  expect(onAzure.event_delay_p95_ms, 'the 95th percentile event delay on Azure').toBeLessThan(2_000)
})
