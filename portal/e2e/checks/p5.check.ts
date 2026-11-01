/**
 * The checker's checks for P5's live lanes, perf block and review video (docs/design/rebuild-plan.md).
 * Run through scripts/checks/p5.sh, which picks the stack and the lane with --grep @laneN.
 * Evidence goes to $EVID/lane-<n>/ with the file names the plan gives.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Locator, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { Backend, LANGGRAPH, REDIS, setMockGithubMode } from '../live/support/stack'
import { devContext } from '../live/support/ui'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p5'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const STATE_WORDS = /Done: |Now: |Not reached yet: |Waiting for a yes|Stopped here|Not needed|Declined/

interface Approval {
  approval_id: string
  digest: string
  actions: { fields: { title: string } }[]
  steps: { index: number; status: string }[]
  you_can_decide: boolean
  why_not: string | null
}

const OPEN_LINK = 'Open in AI Workflow Builder'
/** The card is the same for everyone in the channel, so it names who cannot decide rather than telling the reader. */
const CARD_OWN_WORK = 'Alice can’t decide, because this run is their own work.'
const TEAMS_BUTTON = /^Teams, practice copy/
const TEAMS_PANEL = 'Teams, practice copy'

interface Step {
  key: string
  state: string
  text: string
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = false): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })

async function stepsOf(page: Page): Promise<Step[]> {
  return page
    .locator('ol[aria-label="Steps of this run"] > li[data-state]')
    .evaluateAll((items) => items.map((li, index) => ({ key: String(index), state: (li as HTMLElement).dataset['state'] ?? '', text: (li as HTMLElement).innerText.replace(/\s+/g, ' ').trim() })))
}

async function stepsSaid(page: Page): Promise<string[]> {
  return page.locator('ol[aria-label="Steps of this run"] > li[data-state]').evaluateAll((items) => items.map((li) => (li.textContent ?? '').replace(/\s+/g, ' ').trim()))
}

async function withBackend<T>(act: (backend: Backend) => Promise<T>): Promise<T> {
  const backend = await Backend.connect(BASE_URL)
  try {
    return await act(backend)
  } finally {
    await backend.dispose()
  }
}

async function ticketsOf(backend: Backend, runId: string) {
  return (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
}

async function eventsOf(backend: Backend, runId: string): Promise<{ seq: number; kind: string; data: Record<string, unknown> }[]> {
  return (await backend.get<{ events: { seq: number; kind: string; data: Record<string, unknown> }[] }>('alice', `/api/v1/runs/${runId}/events?after=0`)).events
}

async function watchLine(page: Page, until: (steps: Step[]) => boolean, limitMs = 60_000, everyMs = 100): Promise<{ at: number; states: string }[]> {
  const changes: { at: number; states: string }[] = []
  const start = Date.now()
  while (Date.now() - start < limitMs) {
    const steps = await stepsOf(page).catch(() => [])
    const states = steps.map((s) => s.state).join(',')
    if (states && changes.at(-1)?.states !== states) changes.push({ at: Date.now() - start, states })
    if (steps.length > 0 && until(steps)) break
    await page.waitForTimeout(everyMs)
  }
  return changes
}

async function decidedEvents(backend: Backend, runId: string) {
  return (await eventsOf(backend, runId)).filter((event) => event.kind === 'approval_decided')
}

async function decisionButtons(scope: Page | Locator): Promise<{ approve: number; decline: number }> {
  return {
    approve: await scope.getByRole('button', { name: /^Approve/ }).count(),
    decline: await scope.getByRole('button', { name: /^Decline/ }).count(),
  }
}

function decisionPosts(page: Page): { url: string; body: string | null; status: number }[] {
  const posts: { url: string; body: string | null; status: number }[] = []
  page.on('response', (response) => {
    const request = response.request()
    if (request.method() === 'POST' && request.url().includes('/decisions')) posts.push({ url: new URL(request.url()).pathname, body: request.postData(), status: response.status() })
  })
  return posts
}

async function openTeams(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: TEAMS_BUTTON }).click()
  const drawer = page.getByRole('dialog', { name: TEAMS_PANEL })
  await expect(drawer).toBeVisible()
  return drawer
}

async function scrollToTeamsCard(drawer: Locator, approvalId: string): Promise<Locator> {
  const card = drawer.locator(`li[data-approval-id="${approvalId}"]`)
  await card.scrollIntoViewIfNeeded()
  await expect(card.getByRole('link', { name: OPEN_LINK })).toBeVisible()
  return card
}

async function startWhileWatching(page: Page, useCaseId: string, starter = 'alice'): Promise<string> {
  return page.evaluate(
    async ({ useCaseId, starter }) => {
      const started = await fetch(`/api/v1/use-cases/${useCaseId}/runs`, { method: 'POST', headers: { 'X-Dev-User': starter, 'Idempotency-Key': crypto.randomUUID() } })
      const { run_id: runId } = (await started.json()) as { run_id: string }
      history.pushState(null, '', `/runs/${runId}`)
      dispatchEvent(new PopStateEvent('popstate'))
      return runId
    },
    { useCaseId, starter },
  )
}

const FIRST_WORKING_STEP = 1
const atGate = (steps: Step[]) => steps.some((s) => s.state === 'wait')
const finished = (steps: Step[]) => steps.at(-1)?.state === 'done'

function currentSteps(changes: { states: string }[]): { index: number; state: string }[] {
  return changes.map((change) => {
    const states = change.states.split(',')
    const index = states.findIndex((state) => state === 'now' || state === 'wait')
    return { index, state: states[index] ?? '' }
  })
}

test('@lane1-trunk trunk has no run page', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/runs/run_from_head')
  await expect(h1(page)).toBeVisible()
  const heading = (await h1(page).innerText()).trim()
  await shotTo(page, 1, 'p5-live-run-trunk.png')
  save(1, 'p5-trunk.json', { target: 'trunk', url: page.url(), heading })
  expect(heading).toBe('Page not found')
  await context.close()
})

test('@lane1 alice watches a new check move through each step in order and stop at the gate', async ({ browser }) => {
  await withBackend(async (backend) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const useCaseId = await backend.freshWatchlist('alice')
    await page.goto('/runs/none')
    await expect(h1(page)).toHaveText('Run not found')
    const runId = await startWhileWatching(page, useCaseId)
    const changes = await watchLine(page, atGate, 60_000, 50)
    const current = currentSteps(changes)
    const last = changes.at(-1)?.states ?? ''
    const gate = last.split(',').indexOf('wait')
    await page.waitForTimeout(3_000)
    const later = (await stepsOf(page)).map((s) => s.state).join(',')
    await expect(h1(page)).toHaveText(/waiting for a yes$/)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 1, 'p5-live-run.png')
    const fills = await page.locator('ol[aria-label="Steps of this run"] > li[aria-hidden="true"]').evaluateAll((items) => items.map((li) => getComputedStyle(li).transform))
    const steps = await stepsOf(page)
    save(1, 'p5-live-run.json', { runId, changes, current, gate, statesThreeSecondsLater: later, steps, fills })
    expect(gate, 'the run reached the gate').toBeGreaterThan(0)
    for (let index = FIRST_WORKING_STEP; index < gate; index += 1) {
      expect(current.some((c) => c.index === index && c.state === 'now'), `step ${index} was seen as the current step`).toBe(true)
    }
    expect(current.every((c, i) => i === 0 || c.index >= (current[i - 1]?.index ?? 0)), 'the line only moves forward').toBe(true)
    expect(later, 'it stays at the gate').toBe(last)
    expect(steps.map((s) => s.state)).toEqual([...steps.slice(0, gate).map(() => 'done'), 'wait', ...steps.slice(gate + 1).map(() => 'todo')])
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 bob approves a waiting run and the page shows the ticket created and the run Done', async ({ browser }) => {
  await withBackend(async (backend) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
    await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
    await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    const tickets = await ticketsOf(backend, runId)
    await expect(page.getByRole('main')).toContainText(`Created ${tickets[0]?.key ?? 'nothing'} in Jira.`)
    await expect(page.getByRole('main')).toContainText('Bob approved, and the platform created the ticket.')
    const steps = await stepsOf(page)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 2, 'p5-approved.png', true)
    save(2, 'p5-approved.json', { runId, approvalId, run: await backend.run(runId), tickets, steps })
    expect(tickets).toHaveLength(1)
    expect(steps.every((s) => s.state === 'done')).toBe(true)
    expect((await backend.run(runId)).state).toBe('succeeded')
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 bob declines a waiting run and nothing is written', async ({ browser }) => {
  await withBackend(async (backend) => {
    const { runId } = await backend.waitingRun('alice')
    const before = await backend.tickets()
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await page.getByRole('button', { name: 'Decline' }).click()
    await expect(h1(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
    await expect(page.getByRole('main')).toContainText('Bob declined, so nothing was written.')
    const steps = await stepsOf(page)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 3, 'p5-declined.png', true)
    const after = await backend.tickets()
    save(3, 'p5-declined.json', { runId, run: await backend.run(runId), ticketsBefore: before.length, ticketsAfter: after.length, forThisRun: await ticketsOf(backend, runId), steps })
    expect(after.length).toBe(before.length)
    expect(await ticketsOf(backend, runId)).toEqual([])
    expect(steps.map((s) => s.state).slice(-3)).toEqual(['declined', 'skip', 'done'])
    expect((await backend.run(runId)).state).toBe('rejected')
    assertClean(watch)
    await context.close()
  })
})

async function cannotDecide(browser: Browser, user: 'alice' | 'carol', lane: 4 | 5, file: string, refusal: string, teamsWords: string) {
  return withBackend(async (backend) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const context = await devContext(browser, user)
    const page = await context.newPage()
    const watch = watchPage(page)
    const posts = decisionPosts(page)

    await page.goto(`/runs/${runId}`)
    await expect(h1(page)).toHaveText('1 ticket is waiting for a yes')
    await expect(page.locator('#decision')).toBeFocused()
    await shotTo(page, lane, file)
    const onRunPage = { ...(await decisionButtons(page)), text: await page.getByRole('main').innerText() }

    await page.goto(`/approvals/${approvalId}`)
    await expect(h1(page)).toHaveText('1 ticket is waiting for a yes')
    const onApprovalLink = { ...(await decisionButtons(page)), url: page.url() }

    const card = await scrollToTeamsCard(await openTeams(page), approvalId)
    await expect(card.getByText(teamsWords)).toBeVisible()
    const inTeams = { ...(await decisionButtons(card)), text: await card.innerText() }
    await shotTo(page, lane, file.replace('.png', '-teams.png'))
    await page.keyboard.press('Escape')

    const approval = await backend.get<Approval>(user, `/api/v1/approvals/${approvalId}`)
    const step = approval.steps.find((s) => s.status === 'open')?.index ?? 0
    const answers = await Promise.all(
      (['approve', 'decline'] as const).map(async (verdict) => ({ verdict, ...(await backend.send('POST', user, `/api/v1/approvals/${approvalId}/decisions`, { step, verdict, digest: approval.digest })) })),
    )
    const run = await backend.run(runId)
    const decided = await decidedEvents(backend, runId)
    save(lane, file.replace('.png', '.json'), { user, runId, approval, onRunPage, onApprovalLink, inTeams, answers, runState: run.state, decisionPostsFromPage: posts, decided })

    expect(approval).toMatchObject({ you_can_decide: false, why_not: refusal })
    for (const [where, buttons] of [
      ['run page', onRunPage],
      ['approval link', onApprovalLink],
      ['Teams card', inTeams],
    ] as const) {
      expect({ approve: buttons.approve, decline: buttons.decline }, `no Approve or Decline on the ${where}`).toEqual({ approve: 0, decline: 0 })
    }
    expect(onRunPage.text).toContain(approval.actions[0]?.fields.title ?? '')
    expect(inTeams.text).toContain(OPEN_LINK)
    for (const answer of answers) {
      expect(answer.status, `the API refuses ${answer.verdict}`).toBe(403)
      expect(answer.body).toMatchObject({ refusal })
    }
    expect(run.state).toBe('awaiting_approval')
    expect(posts, 'the page sent no decision').toEqual([])
    expect(decided).toEqual([])
    assertClean(watch)
    await context.close()
    return { onRunPage }
  })
}

test('@lane4 alice sees that someone else must say yes, with no Approve or Decline anywhere', async ({ browser }) => {
  const seen = await cannotDecide(browser, 'alice', 4, 'p5-own-run.png', 'own_work', CARD_OWN_WORK)
  expect(seen.onRunPage.text).toContain('You started this run, so you can’t approve it. Nobody approves their own work.')
})

test('@lane5 carol sees the proposal, with no Approve or Decline anywhere', async ({ browser }) => {
  const seen = await cannotDecide(browser, 'carol', 5, 'p5-not-approver.png', 'not_an_approver', CARD_OWN_WORK)
  expect(seen.onRunPage.text).toContain('Only an Approver can decide.')
  expect(seen.onRunPage.text).toContain('This is exactly what will be written, and nothing else.')
})

test('@lane6 a failed run marks the step that stopped and shows the troubleshooter’s reason below it', async ({ browser }) => {
  await withBackend(async (backend) => {
    await setMockGithubMode('unavailable')
    let runId = ''
    try {
      runId = await backend.startCheck('alice')
      await backend.waitForState(runId, ['failed'], 90_000).catch(async (error: unknown) => {
        if ((await backend.run(runId)).state !== 'failed') throw error
      })
    } finally {
      await setMockGithubMode('ok')
    }
    const advice = await backend.get('alice', `/api/v1/runs/${runId}/troubleshoot`)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(h1(page)).toHaveText(/^Stopped at /)
    await expect(page.locator('#decision')).toBeFocused()
    const failed = page.locator('ol[aria-label="Steps of this run"] > li[data-state="fail"]')
    await expect(failed).toHaveCount(1)
    await expect(failed).toContainText('Stopped here')
    const reason = page.locator('#decision')
    await expect(reason).toContainText('AI troubleshooter')
    await expect(reason).toContainText('What happened')
    await expect(reason).toContainText('What to do')
    const lineBox = await page.locator('ol[aria-label="Steps of this run"]').boundingBox()
    const reasonBox = await reason.boundingBox()
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 6, 'p5-failed.png', true)
    const words = await reason.innerText()
    save(6, 'p5-failed.json', { runId, run: await backend.run(runId), troubleshoot: advice, steps: await stepsOf(page), reasonOnPage: words, lineBox, reasonBox })
    expect((reasonBox?.y ?? 0) > (lineBox?.y ?? 0) + (lineBox?.height ?? 0), 'the reason is below the line').toBe(true)
    expect(words).not.toMatch(/use case|template|room lead|release checker/i)
    assertClean(watch)
    await context.close()
  })
})

test('@lane7 a reload mid-run redraws the steps so far and keeps following new events', async ({ browser }) => {
  await withBackend(async (backend) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const useCaseId = await backend.freshWatchlist('alice')
    await page.goto('/runs/none')
    await expect(h1(page)).toHaveText('Run not found')
    const runId = await startWhileWatching(page, useCaseId)
    const beforeReload = await watchLine(page, (steps) => steps.slice(1).some((s) => s.state === 'done' || s.state === 'now' || s.state === 'wait'))
    const doneBefore = (await stepsOf(page)).filter((s) => s.state === 'done').length
    await page.reload()
    await expect(h1(page)).toBeVisible()
    const firstDrawn = await stepsOf(page)
    const toGate = await watchLine(page, atGate)
    const approvalId = await backend.approvalIdOf(runId)
    const forBob = await backend.get<Approval>('bob', `/api/v1/approvals/${approvalId}`)
    const open = forBob.steps.find((s) => s.status === 'open')
    await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: open?.index ?? 0, verdict: 'approve', digest: forBob.digest }, {}, [201])
    const toDone = await watchLine(page, finished)
    await expect(h1(page)).toHaveText('1 ticket created in Jira')
    const navigations = await page.evaluate(() => performance.getEntriesByType('navigation').length)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 7, 'p5-reload.png', true)
    save(7, 'p5-reload.json', { runId, beforeReload, doneBefore, firstDrawnAfterReload: firstDrawn, toGate, toDone, navigationsAfterReload: navigations })
    expect(firstDrawn.filter((s) => s.state !== 'todo').length, 'the reload draws the steps reached so far at once').toBeGreaterThanOrEqual(doneBefore)
    expect(toDone.at(-1)?.states.split(',').every((s) => s === 'done'), 'the page followed the run to Done without another reload').toBe(true)
    assertClean(watch)
    await context.close()
  })
})

test('@lane8 the Teams link opens a run at the decision, and a yes there shows on the Teams card', async ({ browser }) => {
  await withBackend(async (backend) => {
    const first = await backend.waitingRun('alice')
    const message = (await backend.teamsMessages()).find((m) => m.approval_id === first.approvalId)
    expect(message, 'a Teams message for the first run').toBeDefined()
    const linkPath = new URL(message?.link ?? '/', BASE_URL).pathname
    const secondRun = await backend.addAndCheck('alice', REDIS)
    await backend.waitForState(secondRun, ['awaiting_approval'])
    const second = { runId: secondRun, approvalId: await backend.approvalIdOf(secondRun) }

    const fresh = await devContext(browser, 'bob')
    const linkPage = await fresh.newPage()
    const freshWatch = watchPage(linkPage)
    await linkPage.goto(linkPath)
    await expect(h1(linkPage)).toHaveText('1 ticket is waiting for a yes')
    await expect(linkPage.locator('#decision')).toBeFocused()
    const freshLoad = { link: message?.link, url: linkPage.url(), focused: await linkPage.evaluate(() => document.activeElement?.id ?? ''), buttons: await decisionButtons(linkPage) }
    assertClean(freshWatch)
    await fresh.close()

    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    const firstCard = await scrollToTeamsCard(await openTeams(page), first.approvalId)
    await firstCard.getByRole('link', { name: OPEN_LINK }).click()
    await expect(page).toHaveURL(new RegExp(`/approvals/${first.approvalId}$`))
    await expect(page.locator('#decision')).toBeFocused()
    await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
    const panelLink = { url: page.url(), heading: await h1(page).innerText(), focused: await page.evaluate(() => document.activeElement?.id ?? '') }

    // Like real Teams, the card has no Approve button: Bob opens the approval page from it and decides there.
    await page.goto('/')
    await page.evaluate(() => {
      ;(window as unknown as { kept: boolean }).kept = true
    })
    const posts = decisionPosts(page)
    const forBob = await backend.get<Approval>('bob', `/api/v1/approvals/${second.approvalId}`)
    const secondCard = await scrollToTeamsCard(await openTeams(page), second.approvalId)
    const inTeams = await decisionButtons(secondCard)
    await secondCard.getByRole('link', { name: OPEN_LINK }).click()
    await expect(page).toHaveURL(new RegExp(`/approvals/${second.approvalId}$`))
    await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
    await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    const decidedCard = await scrollToTeamsCard(await openTeams(page), second.approvalId)
    await expect(decidedCard.getByText('Approved by Bob')).toBeVisible({ timeout: 30_000 })
    await shotTo(page, 8, 'p5-teams-approve.png')
    const kept = await page.evaluate(() => (window as unknown as { kept?: boolean }).kept === true)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: TEAMS_PANEL })).toBeHidden()
    save(8, 'p5-teams-approve.json', {
      first,
      second,
      freshLoad,
      panelLink,
      inTeams,
      posts,
      secondRun: await backend.run(second.runId),
      firstRun: await backend.run(first.runId),
      ticketsForSecond: await ticketsOf(backend, second.runId),
      pageNotReloaded: kept,
    })
    expect(linkPath).toBe(`/approvals/${first.approvalId}`)
    expect(freshLoad).toMatchObject({ focused: 'decision', buttons: { approve: 1, decline: 1 } })
    expect(freshLoad.url.endsWith(linkPath)).toBe(true)
    expect(panelLink.focused).toBe('decision')
    expect(inTeams, 'no Approve or Decline on the Teams card').toEqual({ approve: 0, decline: 0 })
    expect(posts.map((post) => post.url), 'the approval page posted to the second run’s approval only').toEqual([`/api/v1/approvals/${second.approvalId}/decisions`])
    expect(JSON.parse(posts[0]?.body ?? '{}')).toEqual({ step: 0, verdict: 'approve', digest: forBob.digest })
    expect(kept, 'the card’s link and the yes worked without a reload').toBe(true)
    expect((await backend.run(first.runId)).state, 'opening the link decides nothing').toBe('awaiting_approval')
    assertClean(watch)
    await context.close()
  })
})

interface MotionSeen {
  frames: number
  maxRunning: number
  names: string[]
}

async function sampleMotion(page: Page): Promise<() => Promise<MotionSeen>> {
  await page.evaluate(() => {
    const seen = { frames: 0, maxRunning: 0, names: [] as string[] }
    ;(window as unknown as { motionSeen: typeof seen }).motionSeen = seen
    setInterval(() => {
      const running = document.getAnimations().filter((a) => a.playState === 'running')
      seen.frames += 1
      seen.maxRunning = Math.max(seen.maxRunning, running.length)
      for (const a of running) {
        const effect = a.effect as KeyframeEffect | null
        const name = `${'animationName' in a ? String((a as CSSAnimation).animationName) : 'transition'} on ${effect?.target?.tagName.toLowerCase() ?? '?'}${effect?.pseudoElement ?? ''}`
        if (!seen.names.includes(name)) seen.names.push(name)
      }
    }, 5)
  })
  return () => page.evaluate(() => (window as unknown as { motionSeen: MotionSeen }).motionSeen)
}

test('@lane9 reduced motion, words for every step, and axe on the run page and the Teams panel', async ({ browser }) => {
  await withBackend(async (backend) => {
    const playRun = async (reducedMotion: boolean) => {
      const context = await devContext(browser, 'alice', { reducedMotion })
      const page = await context.newPage()
      const useCaseId = await backend.freshWatchlist('alice')
      await page.goto('/runs/none')
      await expect(h1(page)).toHaveText('Run not found')
      const readMotion = await sampleMotion(page)
      const runId = await startWhileWatching(page, useCaseId)
      const toGate = await watchLine(page, atGate)
      const said = await stepsSaid(page)
      const approvalId = await backend.approvalIdOf(runId)
      const forBob = await backend.get<Approval>('bob', `/api/v1/approvals/${approvalId}`)
      await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest: forBob.digest }, {}, [201])
      const toDone = await watchLine(page, finished)
      await page.waitForTimeout(1_000)
      const seen = await readMotion()
      const saidDone = await stepsSaid(page)
      await context.close()
      return { runId, toGate, toDone, framesSampled: seen.frames, maxRunning: seen.maxRunning, animating: seen.names, said, saidDone }
    }
    const control = await playRun(false)
    const motion = await playRun(true)

    const { runId, approvalId } = await backend.waitingRun('alice')
    const runs: Record<string, unknown>[] = []
    const panel: Record<string, unknown>[] = []
    for (const [width, phone] of [
      ['1440', false],
      ['390', true],
    ] as const) {
      for (const reducedMotion of [false, true]) {
        const context = await devContext(browser, 'bob', { phone, reducedMotion })
        const page = await context.newPage()
        await page.goto(`/runs/${runId}`)
        await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
        await page.waitForTimeout(500)
        const readMotion = await sampleMotion(page)
        const drawer = await openTeams(page)
        await scrollToTeamsCard(drawer, approvalId)
        await page.waitForTimeout(800)
        await page.keyboard.press('Escape')
        await expect(drawer).toBeHidden()
        await page.waitForTimeout(500)
        panel.push({ width, reducedMotion, ...(await readMotion()) })
        await context.close()
      }
      const context = await devContext(browser, 'bob', { phone, reducedMotion: true })
      const page = await context.newPage()
      await page.goto(`/runs/${runId}`)
      await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
      for (const [where, open] of [
        ['run page', false],
        ['Teams panel', true],
      ] as const) {
        if (open) await scrollToTeamsCard(await openTeams(page), approvalId)
        const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
        runs.push({
          where,
          width,
          axe: result.testEngine.version,
          violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
          passes: result.passes.length,
        })
        await page.screenshot({ path: path.join(laneDir(9), `p5-axe-${where.replace(' ', '-')}-${width}.png`) })
      }
      await context.close()
    }
    const violations = runs.flatMap((r) => (r['violations'] as { id: string }[]).map((v) => `${String(r['where'])} @${String(r['width'])}: ${v.id}`))
    save(9, 'p5-reduced-motion-axe.json', { tags: WCAG_22_AA, motion, controlWithMotionOn: control, teamsPanelOpenAndClose: panel, axe: runs, totalViolations: violations.length })
    expect(control.maxRunning, 'with motion on, the sampler sees the run animate').toBeGreaterThan(0)
    expect(motion.maxRunning, `animations running under reduced motion: ${motion.animating.join(', ')}`).toBe(0)
    expect([...motion.said, ...motion.saidDone].filter((said) => !STATE_WORDS.test(said)), 'steps that do not say their state in words').toEqual([])
    expect(motion.framesSampled, 'samples taken while the run played').toBeGreaterThan(100)
    for (const sample of panel as unknown as ({ width: string; reducedMotion: boolean } & MotionSeen)[]) {
      expect(sample.frames, `samples while the Teams panel opened and closed at ${sample.width}`).toBeGreaterThan(50)
      if (sample.reducedMotion) expect(sample.maxRunning, `animations while the Teams panel opened and closed at ${sample.width}: ${sample.names.join(', ')}`).toBe(0)
      else expect(sample.maxRunning, `with motion on, the sampler sees the Teams panel animate at ${sample.width}`).toBeGreaterThan(0)
    }
    expect(violations, 'axe violations').toEqual([])
  })
})

async function approvePage(browser: Browser, runId: string) {
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const watch = watchPage(page)
  const posts = decisionPosts(page)
  await page.goto(`/runs/${runId}`)
  const approve = page.getByRole('button', { name: 'Approve 1 ticket' })
  await expect(approve).toBeVisible()
  return { context, page, watch, approve, posts }
}

async function oneDecision(backend: Backend, runId: string) {
  await backend.waitForState(runId, ['succeeded'])
  await new Promise((resolve) => setTimeout(resolve, 1_500))
  return { decided: await decidedEvents(backend, runId), tickets: await ticketsOf(backend, runId), state: (await backend.run(runId)).state }
}

test('@lane10 pressing Approve twice, however it is pressed, records one decision and one set of tickets', async ({ browser }) => {
  test.setTimeout(600_000)
  await withBackend(async (backend) => {
    const out: Record<string, { runId: string; posts?: unknown[]; decided: unknown[]; tickets: unknown[]; state: string } & Record<string, unknown>> = {}
    const pressTwice = async (name: string, press: (approve: Locator, page: Page) => Promise<void>) => {
      const { runId } = await backend.waitingRun('alice')
      const tab = await approvePage(browser, runId)
      await press(tab.approve, tab.page)
      await expect(h1(tab.page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
      out[name] = { runId, posts: tab.posts, ...(await oneDecision(backend, runId)) }
      assertClean(tab.watch)
      await tab.context.close()
    }

    await pressTwice('twoClicksInOneTask', async (approve) => {
      await approve.evaluate((button: HTMLButtonElement) => {
        button.click()
        button.click()
      })
    })
    await pressTwice('mouseDoubleClick', async (approve) => {
      await approve.dblclick()
    })
    await pressTwice('enterEnterSpace', async (approve, page) => {
      await approve.focus()
      await page.keyboard.press('Enter')
      await page.keyboard.press('Enter')
      await page.keyboard.press('Space')
    })

    const both = await backend.waitingRun('alice')
    const tab1 = await approvePage(browser, both.runId)
    const tab2 = await approvePage(browser, both.runId)
    await Promise.all([tab1.approve.evaluate((b: HTMLButtonElement) => b.click()), tab2.approve.evaluate((b: HTMLButtonElement) => b.click())])
    await expect(h1(tab1.page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    await expect(h1(tab2.page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    await tab2.page.screenshot({ path: path.join(laneDir(10), 'p5-two-tabs.png'), fullPage: true })
    out['twoTabs'] = { runId: both.runId, posts: [...tab1.posts, ...tab2.posts], alerts: [...(await tab1.page.getByRole('alert').allInnerTexts()), ...(await tab2.page.getByRole('alert').allInnerTexts())], ...(await oneDecision(backend, both.runId)) }
    await tab1.context.close()
    await tab2.context.close()

    const raw = await backend.waitingRun('alice')
    const view = await backend.get<Approval>('bob', `/api/v1/approvals/${raw.approvalId}`)
    const body = { step: 0, verdict: 'approve', digest: view.digest }
    const answers = await Promise.all([1, 2, 3].map(() => backend.send('POST', 'bob', `/api/v1/approvals/${raw.approvalId}/decisions`, body)))
    out['threeRawPostsAtOnce'] = { runId: raw.runId, statuses: answers.map((answer) => answer.status), ...(await oneDecision(backend, raw.runId)) }

    save(10, 'p5-double-click.json', out)
    for (const [name, result] of Object.entries(out)) {
      expect(result.decided, `${name}: one approval_decided`).toHaveLength(1)
      expect(result.tickets, `${name}: one ticket`).toHaveLength(1)
      expect(result.state, `${name}: the run is done`).toBe('succeeded')
    }
    for (const name of ['twoClicksInOneTask', 'mouseDoubleClick', 'enterEnterSpace']) expect(out[name]?.posts, `${name}: the page sent one decision`).toHaveLength(1)
    expect(out['twoTabs']?.['alerts'], 'neither tab shows an error').toEqual([])
    expect((out['threeRawPostsAtOnce']?.['statuses'] as number[]).filter((status) => status === 201), 'one of three raw posts recorded the decision').toHaveLength(1)
  })
})

async function doneRun(backend: Backend): Promise<string> {
  const done = (await backend.runs('alice')).find((run) => run.state === 'succeeded' && run.outcome === 'written')
  if (done) return done.run_id
  const { runId, approvalId } = await backend.waitingRun('alice', [LANGGRAPH])
  const approval = await backend.get<Approval>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest: approval.digest }, {}, [201])
  await backend.waitForState(runId, ['succeeded'])
  return runId
}

test('@perf largest contentful paint of a done run', async ({ browser }) => {
  const runId = await withBackend(doneRun)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`, { waitUntil: 'load' })
  await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 30_000 })
  await page.waitForTimeout(1_500)
  const measured = await page.evaluate(
    () =>
      new Promise<{ entries: { startTime: number; element: string }[] }>((resolve) => {
        const entries: { startTime: number; element: string }[] = []
        const observer = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as (PerformanceEntry & { element: Element | null })[]) {
            entries.push({ startTime: e.startTime, element: e.element ? `${e.element.tagName.toLowerCase()} "${(e.element.textContent ?? '').trim().slice(0, 40)}"` : 'gone' })
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => {
          observer.disconnect()
          resolve({ entries })
        }, 500)
      }),
  )
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, runId, lcp: last?.startTime ?? -1, element: last?.element ?? '', entries: measured.entries })
  await context.close()
})

test('@review-video a run that waits, is approved on its page, and finishes', async ({ browser }) => {
  test.setTimeout(180_000)
  await withBackend(async (backend) => {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
      locale: 'en-SG',
      timezoneId: 'Asia/Singapore',
    })
    await context.addInitScript(() => window.localStorage.setItem('portal.dev-user', 'bob'))
    const page = await context.newPage()
    const video = page.video()
    const useCaseId = await backend.freshWatchlist('alice')
    await page.goto('/')
    await expect(h1(page)).toBeVisible()
    await page.waitForTimeout(2_500)
    await page.goto('/runs/none')
    await expect(h1(page)).toBeVisible()
    await startWhileWatching(page, useCaseId)
    await watchLine(page, atGate)
    await page.waitForTimeout(4_000)
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    await page.waitForTimeout(4_500)
    await page.locator('#decision').scrollIntoViewIfNeeded()
    await page.waitForTimeout(4_000)
    await page.getByRole('button', { name: 'Approve 1 ticket' }).hover()
    await page.waitForTimeout(1_000)
    await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
    await watchLine(page, finished)
    await page.waitForTimeout(4_000)
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    await page.waitForTimeout(4_500)
    await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
    await page.waitForTimeout(5_000)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(2_000)
    await context.close()
    await video?.saveAs(path.join(EVID, 'p5-review.webm'))
  })
})
